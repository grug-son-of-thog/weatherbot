import configparser
import discord
import json
import logging
import random
import re
import requests
import sys

from discord.ext import commands, tasks

config = configparser.ConfigParser()
config.read('config.ini')
TOKEN = config.get('Bot', 'Token')

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='?', intents=intents)

targets = logging.StreamHandler(sys.stdout), logging.FileHandler('weatherBot.log')
logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO, handlers=targets)

def load_subscriptions():
    try:
        with open('subscriptions.json', 'r') as file:
            return json.load(file)
    
    except FileNotFoundError:
        return {}

def save_subscriptions(subscriptions):
    for county_state, data in list(subscriptions.items()):
        logging.debug(county_state + ' ' + str(data))
        remove_empty_subscription(county_state, data)
    
    with open('subscriptions.json', 'w') as file:
        logging.debug(json.dumps(subscriptions, indent=4))
        json.dump(subscriptions, file, indent=4)

def remove_empty_subscription(county_state, data):
    if not data['users']:
        logging.info(f'{county_state} has no subscribers! Removing...')
        subscriptions.pop(county_state)

def get_noaa_zone(county, state):
    county = county.upper()
    state = state.upper()
    with open('zones.dbx', 'r') as file:
        for line in file:
            parts = line.strip().split('|')

            if len(parts) != 11 or parts[0].upper() != state or parts[3].upper() != county:
                logging.debug('Does not match')
                continue

            latitude, longitude = parts[9], parts[10]
            url = f'https://api.weather.gov/points/{latitude},{longitude}'
            response = requests.get(url)

            if response.status_code != 200:
                logging.info(f'Failed to retrieve data from NOAA API. Status Code: {response.status_code}')
                return

            data = response.json()

            if 'properties' not in data or 'county' not in data['properties']:
                logging.info(f'Failed to retrieve county information for {county_state}.')

            county_value = data['properties']['county']
            zone_code = county_value.split('/')[-1]
            return zone_code
    return ''

def remove_existing_alert(data, response_data):
    for existing_alert in data['alerts']:
        if existing_alert not in json.dumps(response_data['features']):
            data['alerts'].remove(existing_alert)
    
    return data

def add_new_alerts(data, event):
    if event not in data['alerts']:
        data['alerts'].append(event)
        new_alerts.append((event, headline, description))
    
    return new_alerts

subscriptions = load_subscriptions()

@bot.event
async def on_ready():
    logging.info(f'Logged in as {bot.user} (ID: {bot.user.id})')
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="DING DINGA DING DING"))
    if not check_weather_alerts.is_running():
        check_weather_alerts.start()

@bot.command()
async def subscribe(ctx, *, location=None):
    user = ctx.author

    if location is None:
        logging.info(f'Invalid subscription request received from from {user} (ID: {user.id}).')
        await ctx.send(f'{user.mention}, please provide a valid location in the format "county, state".')
        return

    match = re.match(r'^([\w\s.,/-]+),\s*([\w\s.-]+)$', location)

    if not match:
        logging.info(f'Invalid subscription request received from from {user} (ID: {user.id}).')
        await ctx.send(f'{user.mention}, please provide a valid location in the format "county, state".')
        return
    
    county = match.group(1).strip().upper()
    state = match.group(2).strip().upper()
    county_state = f'{county}, {state}'
    zone = get_noaa_zone(county, state)

    if not zone:
        logging.info(f'{user} (ID: {user.id}) requested subscription for {county} COUNTY {state} but it could not be found.')
        await ctx.send(f'{user.mention}, failed to retrieve the NOAA zone for {county} COUNTY, {state}.')
        return

    if county_state not in subscriptions:
        subscriptions[county_state] = {
            'county_code': zone,
            'users': [],
            'alerts': []
        }
    
    if user.id in subscriptions[county_state]['users']:
        logging.info(f'{user} (ID: {user.id}) requested duplicate subscripion for {county} COUNTY {state}.')
        await ctx.send(f'{user.mention}, you are already subscribed to alerts for {county} COUNTY, {state}.')
        return

    subscriptions[county_state]['users'].append(user.id)
    existing_alerts = get_existing_alerts(county_state)

    if existing_alerts:
        await alert_user(user, county_state, existing_alerts)
    
    logging.info(f'Subscribing {user} (ID: {user.id}) to alerts for {county} COUNTY, {state}.')
    await ctx.send(f'{user.mention}, you are now subscribed to alerts for {county} COUNTY, {state}.')

    save_subscriptions(subscriptions)

@bot.command()
async def unsubscribe(ctx, *, location=None):
    user = ctx.author
    if location is None:
        subscribed_counties = [county_state for county_state, data in subscriptions.items() if user.id in data['users']]
        
        for county_state in subscribed_counties:
            subscriptions[county_state]['users'].remove(user.id)
        
        logging.info(f'Unsubscribing {user} (ID: {user.id}) from all counties.')
        await ctx.send(f'{user.mention}, you have been unsubscribed from all counties.')
        return

    match = re.match(r'^([\w\s.,/-]+),\s*([\w\s.-]+)$', location)
    
    if not match:
        logging.info(f'Invalid unsubscription request received from from {user} (ID: {user.id}).')
        await ctx.send(f'{user.mention}, please provide a valid location in the format "county, state".')
        return
    
    county = match.group(1).strip().upper()
    state = match.group(2).strip().upper()
    county_state = f'{county}, {state}'
    
    if county_state not in subscriptions or user.id not in subscriptions[county_state]['users']:
        await ctx.send(f'{user.mention}, you are not currently subscribed to alerts for {county} COUNTY, {state}.')
        return

    subscriptions[county_state]['users'].remove(user.id)
    logging.info(f'Unsubscribing {user} (ID: {user.id}) from alerts for {county} COUNTY, {state}.')
    await ctx.send(f'{user.mention}, you have been unsubscribed from alerts for {county} COUNTY, {state}.')
    save_subscriptions(subscriptions)

@bot.command()
async def my_subscriptions(ctx):
    user = ctx.author
    subscribed_counties = [county_state.split(',')[0] for county_state, data in subscriptions.items() if user.id in data['users']]
    
    if not subscribed_counties:
        await ctx.send(f'{user.mention}, you are not subscribed to any counties.')
        return
    
    logging.info(f'{user} (ID: {user.id}) requested their list of subscriptions.')
    await ctx.send(f'{user.mention}, you are subscribed to the following counties: {", ".join(subscribed_counties)}')

@tasks.loop(minutes=5)
async def check_weather_alerts():
    for county_state, data in list(subscriptions.items()):
        zone = data['county_code']
        logging.debug(f'Polling NOAA API for Alert Zone {zone}.')

        if not zone:
            logging.info(f'County code for {county_state} has been corrupted.')
            return

        response = requests.get(f'https://api.weather.gov/alerts/active?zone={zone}')

        if response.status_code != 200:
            logging.info(f'Failed to retrieve data from NOAA API. Status Code: {response.status_code}')
            return

        logging.debug(f'NOAA API responded with code 200.')
        new_alerts = []
        response_data = response.json()
        logging.debug(json.dumps(response_data, indent=4))

        if 'features' not in response_data and len(response_data['features']) == 0:
            return

        for feature in response_data['features']:
            event = feature.get('properties', {}).get('event')
            headline = feature.get('properties', {}).get('headline')
            description = feature.get('properties', {}).get('description')
            data = remove_existing_alerts(data, response_data)
            new_alerts = add_new_alerts(data, event)

        if new_alerts:
            await alert_subscribed_users(county_state, new_alerts)

        subscriptions[county_state] = data
        save_subscriptions(subscriptions)

async def alert_user(user, county_state, alerts):
    split_county_state = county_state.split(',')
    county = split_county_state[0]
    state = split_county_state[1]
    alert_messages = "\n".join([f'**{event}**\n{headline}\n\n{description}' for event, headline, description in alerts])
    await user.send(f'***!!!!!!!! ALERT FOR {county} COUNTY, {state} !!!!!!!!***\n{alert_messages}')

async def alert_subscribed_users(county_state, new_alerts):
    if county_state not in subscriptions:
        return
    
    user_ids = subscriptions[county_state]['users']
    
    for user_id in user_ids:
        user = await bot.fetch_user(user_id)
        if user:
            await alert_user(user, county_state, new_alerts)

def get_existing_alerts(county_state):
    zone = subscriptions[county_state]['county_code']
    if not zone:
        return []
    
    response = requests.get(f'https://api.weather.gov/alerts/active?zone={zone}')
    
    if response.status_code != 200:
        logging.info(f'Failed to retrieve data from NOAA API. Status Code: {response.status_code}')
        return
    
    existing_alerts = []
    response_data = response.json()

    if 'features' not in response_data or len(response_data['features']) <= 0:
        return existing_alerts

    for feature in response_data['features']:
        event = feature.get('properties', {}).get('event')
        headline = feature.get('properties', {}).get('headline')
        description = feature.get('properties', {}).get('description')
        existing_alerts.append((event, headline, description))

    return existing_alerts

bot.run(TOKEN)
