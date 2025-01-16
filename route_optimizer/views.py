
import googlemaps
from datetime import datetime
import pandas as pd
from geopy.distance import geodesic
from django.http import JsonResponse
from rest_framework.decorators import api_view
import os
from django.conf import settings
from shapely.geometry import LineString, Point
import time

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


def get_fuel_stations_by_state(fuel_stations_within_500_miles):
    """
    Filters fuel stations based on unique states from `fuel_stations_within_500_miles`
    and retrieves attributes from the CSV file, sorted by the least retail price.

    Args:
        fuel_stations_within_500_miles (list): List of fuel station dictionaries with a 'state' key.
        fuel_data_file (str): Path to the CSV file containing fuel station data.

    Returns:
        pd.DataFrame: Filtered and sorted DataFrame with specific columns.
    """
    
    
    # Extract unique states from `fuel_stations_within_500_miles`
    unique_states = {station['state'] for station in fuel_stations_within_500_miles}
    
    # Filter the DataFrame based on the unique states
    filtered_data = FUEL_DATA[FUEL_DATA['State'].isin(unique_states)]
    sorted_data = filtered_data.sort_values(by='Retail Price')
    # Select required columns and sort by retail price
    result = sorted_data[['OPIS Truckstop ID', 'Truckstop Name', 'Retail Price']]
    
    return result.head(5)



def calculate_fuel_cost(distance, fuel_price):
    """
    Calculate fuel cost for a given distance and fuel price.
    """
    gallons_needed = distance / VEHICLE_MPG
    return gallons_needed * fuel_price
 
def calculate_total_cost(filtered_fuel_stations, fuel_stations_within_500_miles):
    """
    Calculate the total cost for the first 5 stations based on their distance and retail price.

    Args:
        filtered_fuel_stations (pd.DataFrame): DataFrame containing fuel stations sorted by retail price.
        fuel_stations_within_500_miles (list): List of fuel stations with distance information.

    Returns:
        list: List of dictionaries with 'OPIS Truckstop ID', 'Truckstop Name', and 'total_cost'.
    """
    result = []
    # Convert fuel_stations_within_500_miles to a DataFrame for easier querying
    station_distances = pd.DataFrame(fuel_stations_within_500_miles)

    # Iterate over the first 5 rows in the filtered_fuel_stations
    for _, row in filtered_fuel_stations.head(5).iterrows():
        opis_id = row['OPIS Truckstop ID']
        name = row['Truckstop Name']
        price = row['Retail Price']

        # Find the matching station in the station_distances list
        matching_station = station_distances[
            (station_distances['state'] == row['state']) &
            (station_distances['lat'] == row['lat']) &
            (station_distances['lng'] == row['lng'])
        ]

        if not matching_station.empty:
            distance = matching_station.iloc[0]['distance']  # Extract the distance
            total_cost = calculate_fuel_cost(distance, price)  # Calculate total cost

            result.append({
                'OPIS Truckstop ID': opis_id,
                'Truckstop Name': name,
                'total_cost': round(total_cost, 2)
            })

    return result



@api_view(['POST'])
def optimize_route(request):
    data = request.data
    start_address = data.get('start')
    finish_address = data.get('finish')

    if not start_address or not finish_address:
        return JsonResponse({"error": "Start and finish locations are required."}, status=400)

    # Get route data
    directions_result = gmaps.directions(
        origin=start_address,
        destination=finish_address,
        mode="driving",
        departure_time=datetime.now()
    )

    if not directions_result:
        return JsonResponse({"error": "Failed to fetch route."}, status=400)

    # Extract route and start coordinates
    route = directions_result[0]['legs'][0]['steps']
    start_coords = directions_result[0]['legs'][0]['start_location']

    # Function to check if the distance from the start location is within 500 miles
    def is_within_500_miles(coord, start_coords):
        return geodesic((start_coords['lat'], start_coords['lng']), coord).miles <= 500

    # List to hold fuel stations within 500 miles
    fuel_stations_within_500_miles = []

    # Iterate over the steps (each step represents a part of the journey)
    for step in route:
        location = step['end_location']
        
        # Search for fuel stations near this location
        places_result = gmaps.places_nearby(
            location=(location['lat'], location['lng']),
            radius=5000,  # Search within a 5km radius (adjustable)
            type='gas_station'
        )
        
        # Extract relevant fuel station info
        if places_result.get('results'):
            for place in places_result['results']:
                # Check if the location is within 500 miles from the start
                if is_within_500_miles((place['geometry']['location']['lat'], place['geometry']['location']['lng']), start_coords):
                    # Reverse geocode to get detailed address components
                    reverse_geocode_result = gmaps.reverse_geocode((place['geometry']['location']['lat'], place['geometry']['location']['lng']))
                    state = None
                    
                    # Extract the short name of the state from the address components
                    if reverse_geocode_result:
                        for component in reverse_geocode_result[0]['address_components']:
                            if 'administrative_area_level_1' in component['types']:
                                state = component.get('short_name', None)  # Use the short_name instead of long_name
                                break
                    
                    # Calculate the distance from the start location to the fuel station
                    fuel_station_coords = (place['geometry']['location']['lat'], place['geometry']['location']['lng'])
                    distance = geodesic((start_coords['lat'], start_coords['lng']), fuel_station_coords).miles
                    
                    # Add the fuel station information, including state and distance
                    fuel_station_info = {
                        'lat': place['geometry']['location']['lat'],
                        'lng': place['geometry']['location']['lng'],
                        'formatted_address': place['vicinity'],
                        'state': state,  # State as short name
                        'distance': distance  # Distance to the fuel station
                    }
                    fuel_stations_within_500_miles.append(fuel_station_info)
    filtered_fuel_stations = get_fuel_stations_by_state(fuel_stations_within_500_miles)
    #top_stations_with_costs = calculate_total_cost(filtered_fuel_stations, fuel_stations_within_500_miles)
    # Convert the DataFrame to JSON
    filtered_fuel_stations_json = filtered_fuel_stations.to_json(orient='records')

    print(filtered_fuel_stations_json)
    # Display the result
    
    # Response with the map and fuel stations within 500 miles
    response_data = {
        "route_map": f"https://www.google.com/maps/dir/?api=1&origin={start_address}&destination={finish_address}",
        
        "optimal_stations":filtered_fuel_stations_json,
        "direction": directions_result
    }
    
    return JsonResponse(response_data)

    
    