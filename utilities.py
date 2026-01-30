import json
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

dotenv_path = Path('.') / 'config' / '.env'
load_dotenv(dotenv_path)

api_key=os.getenv('API_KEY')


def get_movie_poster_url(api_key, movie_title):
    # 1. Search for the movie to get the 'poster_path'
    search_url = f"https://api.themoviedb.org{api_key}&query={movie_title}"
    
    try:
        response = requests.get(search_url)
        response.raise_for_status() # Raise an exception for bad status codes
        data = response.json()

        if not data['results']:
            return "Movie not found."

        # Get the poster path from the first search result
        poster_path = data['results'][0]['poster_path']
        if not poster_path:
            return "Poster not available for this movie."

        # 2. Construct the full image URL
        # The base URL and available sizes can be retrieved from the /configuration API
        # A typical secure base URL is 'https://image.tmdb.org'
        BASE_IMAGE_URL = "https://image.tmdb.org"
        # Choose a desired image size (e.g., 'w500', 'original', 'w185')
        IMAGE_SIZE = "w500" 

        full_poster_url = f"{BASE_IMAGE_URL}{IMAGE_SIZE}{poster_path}"
        return full_poster_url

    except requests.exceptions.RequestException as e:
        return f"An error occurred: {e}"

# # Example usage
# poster_url = get_movie_poster_url(API_KEY, MOVIE_TITLE)
# print(f"Poster URL for '{MOVIE_TITLE}': {poster_url}")

#This is being added because the HTML form returns an empty string if the form is left blank. SQLALCHEMY doesnt convert it '' to none 
def clean_int(value):
    # Returns an integer if possible, else None
    if value is None or str(value).strip() == '':
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None

