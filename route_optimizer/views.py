
import googlemaps
from datetime import datetime
import pandas as pd
from geopy.distance import geodesic
from django.http import JsonResponse
from rest_framework.decorators import api_view
import os
from django.conf import settings

# Constants
VEHICLE_RANGE = 500  # in miles
VEHICLE_MPG = 10  # miles per gallon
API_KEY = settings.GOOGLE_MAPS_API_KEY
FUEL_DATA_FILE = os.path.join('route_optimizer', 'data', 'fuel-prices-for-be-assessment.csv')
GEOCODED_DATA_FILE = "geocoded_fuel_data.csv"

# Load fuel price data
FUEL_DATA = pd.read_csv(FUEL_DATA_FILE)

# Initialize Google Maps client
gmaps = googlemaps.Client(key=API_KEY)


def preprocess_fuel_data():
    """
    Geocode all fuel station addresses and add latitude and longitude.
    """
    global FUEL_DATA  # Declare FUEL_DATA as global before referencing it
    if not os.path.exists(GEOCODED_DATA_FILE):
        latitudes, longitudes = [], []
        for _, row in FUEL_DATA.iterrows():
            address = f"{row['Address']}, {row['City']}, {row['State']}"
            geocode_result = gmaps.geocode(address)
            if geocode_result:
                location = geocode_result[0]['geometry']['location']
                latitudes.append(location['lat'])
                longitudes.append(location['lng'])
            else:
                latitudes.append(None)
                longitudes.append(None)

        FUEL_DATA["Latitude"] = latitudes
        FUEL_DATA["Longitude"] = longitudes
        FUEL_DATA.to_csv(GEOCODED_DATA_FILE, index=False)
    else:
        FUEL_DATA = pd.read_csv(GEOCODED_DATA_FILE)



def calculate_fuel_cost(distance, fuel_price):
    """
    Calculate fuel cost for a given distance and fuel price.
    """
    gallons_needed = distance / VEHICLE_MPG
    return gallons_needed * fuel_price


def find_fuel_stations_within_range(route_points):
    """
    Find fuel stations within the specified range from the route.
    """
    eligible_stops = []
    for point in route_points:
        for _, stop in FUEL_DATA.iterrows():
            stop_location = (stop['Latitude'], stop['Longitude'])
            if pd.notna(stop_location).all():  # Ensure valid coordinates
                route_location = (point['lat'], point['lng'])
                distance_to_stop = geodesic(stop_location, route_location).miles

                if distance_to_stop <= VEHICLE_RANGE:
                    stop_data = stop.copy()
                    stop_data['distance_to_route'] = distance_to_stop
                    eligible_stops.append(stop_data)

    return pd.DataFrame(eligible_stops)


@api_view(['POST'])
def optimize_route(request):
    preprocess_fuel_data()

    data = request.data
    start_address = data.get('start')
    finish_address = data.get('finish')

    if not start_address or not finish_address:
        return JsonResponse({"error": "Start and finish locations are required."}, status=400)

    # Get route data
    directions_result = gmaps.directions(start_address, finish_address, mode="driving", departure_time=datetime.now())
    if not directions_result:
        return JsonResponse({"error": "Failed to fetch route."}, status=400)

    # Extract route geometry
    route_legs = directions_result[0]['legs'][0]
    total_distance = route_legs['distance']['value'] / 1609.34  # Convert meters to miles
    route_points = gmaps.elevation_along_path(directions_result[0]['overview_polyline']['points'], 100)

    # Find fuel stations within range
    eligible_stations = find_fuel_stations_within_range(route_points)
    if eligible_stations.empty:
        return JsonResponse({"error": "No fuel stations found within the route."}, status=400)

    # Select the station with the lowest price
    cheapest_station = eligible_stations.loc[eligible_stations['Retail Price'].idxmin()]

    # Calculate the total fuel cost
    total_cost = calculate_fuel_cost(total_distance, cheapest_station['Retail Price'])

    # Prepare response data
    response_data = {
        "route_map": f"https://www.google.com/maps/dir/?api=1&origin={start_address}&destination={finish_address}",
        "cheapest_station": {
            "name": cheapest_station["Truckstop Name"],
            "address": cheapest_station["Address"],
            "city": cheapest_station["City"],
            "state": cheapest_station["State"],
            "price": cheapest_station["Retail Price"],
        },
        "total_cost": round(total_cost, 2),
    }

    return JsonResponse(response_data)
