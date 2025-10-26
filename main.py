import requests
from lxml import html
import datetime
import pytz

import datetime
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# read email and password from environment variables if they exist
if "BAHNAPP_EMAIL" in os.environ:
	email = os.environ["BAHNAPP_EMAIL"]
else:
	email = input("Enter your BahnApp email: ")
if "BAHNAPP_PASSWORD" in os.environ:
	password = os.environ["BAHNAPP_PASSWORD"]
else:
	password = input("Enter your BahnApp password: ")

SCOPES = ["https://www.googleapis.com/auth/calendar"]

creds = None
# The file token.json stores the user's access and refresh tokens, and is
# created automatically when the authorization flow completes for the first
# time.
if os.path.exists("token.json"):
	creds = Credentials.from_authorized_user_file("token.json", SCOPES)
# If there are no (valid) credentials available, let the user log in.
if not creds or not creds.valid:
	if creds and creds.expired and creds.refresh_token:
		creds.refresh(Request())
	else:
		flow = InstalledAppFlow.from_client_secrets_file(
			"credentials.json", SCOPES
		)
		creds = flow.run_local_server(port=0)
		# Save the credentials for the next run
		with open("token.json", "w") as token:
			token.write(creds.to_json())

service = build("calendar", "v3", credentials=creds)


def get_bahnapp_data(email, password):
	url = "https://bahnapp.online/user/login/?type=login"
	payload = "submitLogin=1&email=" + email + "&password=" + password
	headers = {
	'Accept-Language': 'en-US,en;q=0.9',
	'Content-Type': 'application/x-www-form-urlencoded',
	}
	response = requests.request("POST", url, headers=headers, data=payload)

	url = "https://bahnapp.online/route/history/"
	headers = {
	'Accept-Language': 'en-US,en;q=0.9',
	}
	response = requests.request("GET", url, headers=headers, cookies=response.cookies)

	if "Implerstraße" in response.text:
		print("Login successful and route history accessed.")
	else:
		print("Failed to access route history.")


	def calculate_actual_time(date, original_time_str, delay_minutes):
		date_obj = datetime.datetime.strptime(date, "%Y-%m-%d")
		time_obj = datetime.datetime.strptime(original_time_str, "%H:%M").time()
		original_datetime = datetime.datetime.combine(date_obj, time_obj)
		localized_dt = pytz.timezone("Europe/Berlin").localize(original_datetime)
		
		if delay_minutes:
			delay_minutes_int = int(delay_minutes[0])
			final_datetime = localized_dt + datetime.timedelta(minutes=delay_minutes_int)
		else:
			final_datetime = localized_dt
		return final_datetime


	doc = html.fromstring(response.content)
	# trips is a combination of the list doc.xpath('//div[@class="RouteResult"]') and doc.xpath('//div[@class="RouteResult WithTransfer"]')
	trips = doc.xpath('//div[@class="RouteResult"] | //div[@class="RouteResult WithTransfer"]')
	trip_data_list = []
	for trip in trips:
		href = trip.xpath('../../@href')[0]
		date = href.split("date=")[1].split("&")[0]
	
		originaldeparturetime = trip.xpath('.//div[@class="DepartureTime"]/div[@class="Time Heavy"]/text() | .//div[@class="DepartureTime"]/div[@class="Time RealTimeLight"]/text()')[0]
		delaydeparturetime = trip.xpath('.//div[@class="DepartureTime"]/div/span[@class="Delay RealTimeLight PastTime"]/text() | .//div[@class="DepartureTime"]/div/span[@class="Delay Heavy PastTime"]/text()')
	
		originalarrivaltime = trip.xpath('.//div[@class="ArrivalTime"]/div[@class="Time Heavy"]/text() | .//div[@class="ArrivalTime"]/div[@class="Time RealTimeLight"]/text()')[0]
		delayarrivaltime = trip.xpath('.//div[@class="ArrivalTime"]/div/span[@class="Delay RealTimeLight PastTime"]/text() | .//div[@class="ArrivalTime"]/div/span[@class="Delay Heavy PastTime"]/text()')
		
		if originaldeparturetime == []:
			print(f"Could not find original departure time for trip: {html.tostring(trip)}")
			continue

	
		finaldeparturetime_dt = calculate_actual_time(date, originaldeparturetime, delaydeparturetime)
		finalarrivaltime_dt = calculate_actual_time(date, originalarrivaltime, delayarrivaltime)
	
  
		departurestation = trip.xpath('.//div[@class="DepartureStation"]/text() | .//div[@class="DepartureStation WithCapacity"]/text() | .//div[@class="DepartureStation StrikeThrough WarningColor"]/text() | .//div[@class="DepartureStation StrikeThrough WarningColor WithCapacity"]/text()')[0]
		destinationstation = trip.xpath('.//div[@class="DestinationStation"]/text() | .//div[@class="DestinationStation StrikeThrough WarningColor"]/text()')[0]
      
		trip_data = {
			"final_departure_time": finaldeparturetime_dt,
			"final_arrival_time": finalarrivaltime_dt,
			"summary": f"{departurestation} -> {destinationstation}",
		}
		trip_data_list.append(trip_data)
	
	return trip_data_list



def get_gcal_events():
	# Call the Calendar API
	print("Getting the last 10 events")
	events_result = (
		service.events()
		.list(
			calendarId="primary",
			timeMax=datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
			timeMin=(datetime.datetime.now(tz=datetime.timezone.utc)-datetime.timedelta(days=14)).isoformat(),
			maxResults=100,
			singleEvents=True,
			# sort by mostz recent finished events
			orderBy="updated",
		)
		.execute()
	)
	events = events_result.get("items", [])

	# Filter events by both conditions
	filtered_events = [
		event for event in events
		if (
			"summary" in event and "->" in event["summary"]
		) and (
			"description" in event and "https://bahnapp.link/route/" in event["description"]
		)
	]

	if not filtered_events:
		print("No upcoming events found.")
		return

	return filtered_events

def compare_bahnapp_with_gcal():
	bahnapp_trips = get_bahnapp_data(email, password)
	gcal_events = get_gcal_events()
	seven_days_ago = datetime.datetime.now(pytz.timezone("Europe/Berlin")) - datetime.timedelta(days=7)
	recent_bahnapp_trips = [trip for trip in bahnapp_trips if trip["final_departure_time"] >= seven_days_ago]

	differing_trips = []
	for trip in recent_bahnapp_trips:
		trip_found = False
		for event in gcal_events:
			event_start_str = event["start"].get("dateTime", event["start"].get("date"))
			event_start_dt = datetime.datetime.fromisoformat(event_start_str).astimezone(pytz.timezone("Europe/Berlin"))
			if (
				trip["summary"] in event["summary"] and
				abs((trip["final_departure_time"] - event_start_dt).total_seconds()) == 0
			):
				trip_found = True
				break
		if not trip_found:
			differing_trips.append(trip)
	return differing_trips

def add_trips_to_gcal(trips):
	for trip in trips:
		event = {
			'summary': trip['summary'],
			'start': {
				'dateTime': trip['final_departure_time'].isoformat(),
				'timeZone': 'Europe/Berlin',
			},
			'end': {
				'dateTime': (trip['final_arrival_time'].isoformat()),
				'timeZone': 'Europe/Berlin',
			},
			'description': 'Imported using https://github.com/louisa-uno/bahnapp-to-cal',
		}
		event = service.events().insert(calendarId='primary', body=event).execute()
		print(f"Event created: {event.get('htmlLink')}")
	
	
 

differing_trips = compare_bahnapp_with_gcal()
for trip in differing_trips:
	print(f"Trip not in GCal: {trip['summary']} at {trip['final_departure_time']}")
add_trips_to_gcal(differing_trips)

