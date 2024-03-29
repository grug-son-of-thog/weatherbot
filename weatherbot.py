import asyncio
import configparser
import discord
import json
import logging
import random
import re
import requests
import sys

from discord.ext import commands, tasks
from urllib.request import urlopen

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
    for county_code, data in list(subscriptions.items()):
        logging.debug(county_code + ' ' + str(data))
        remove_empty_subscription(county_code, data)
    
    with open('subscriptions.json', 'w') as file:
        logging.debug(json.dumps(subscriptions, indent=4))
        json.dump(subscriptions, file, indent=4)

def remove_empty_subscription(county_code, data):
    if not data['users']:
        logging.info(f'{county_code} has no subscribers! Removing...')
        subscriptions.pop(county_code)

async def add_new_alerts(data, event, headline, description):
    new_alerts = []
    if event not in data['alerts']:
        data['alerts'].append(event)
        new_alerts.append((event, headline, description))

    return new_alerts

def remove_existing_alert(data, response_data):
    for existing_alert in data['alerts']:
        if existing_alert not in json.dumps(response_data['features']):
            data['alerts'].remove(existing_alert)
    
    return data

def get_existing_alerts(county_code):
    county_state = f"{subscriptions[county_code]['county']}, {subscriptions[county_code]['state']}"
    zone = county_code

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

async def get_noaa_zone(ctx, county, state):
    user = ctx.author
    county = county.upper()
    state = state.upper()
    matches = []
    match = []
    
    with urlopen('https://www.weather.gov/source/gis/Shapefiles/County/bp08mr23.dbx') as file:
        for byte_line in file:
            string_line = byte_line.decode('utf-8')
            parts = string_line.strip().split('|')

            if len(parts) != 11 or parts[0].upper() != state or county not in parts[5].upper():
                logging.debug('Line is either malformed or does not match.')
                continue

            latitude, longitude = parts[9], parts[10]
            url = f'https://api.weather.gov/points/{latitude},{longitude}'
            response = requests.get(url)

            if response.status_code != 200:
                logging.info(f'Failed to retrieve data from NOAA API. Status Code: {response.status_code}')
                return ['','','']

            data = response.json()

            if 'properties' not in data or 'county' not in data['properties']:
                logging.debug(f'Failed to retrieve county information for {county_state}.')
                return ['','','']

            county_value = data['properties']['county']
            zone_code = county_value.split('/')[-1]
            parts.append(zone_code)
            matches.append(parts)

        if len(matches) > 10:
            await ctx.send(f'{user.mention}, too many subzones exist. The maximum allowed is 10')
            return
        
        elif len(matches) > 1:
            match = await choose_subzone(ctx, matches, None)
        
        elif len(matches) == 1:
            match = matches[0]

        if not match:
            await ctx.send(f'{user.mention}, Unable to find a county matching the provided values. Please try again.')
            return ['','','']
        
        if match[0] == 'Timeout':
            logging.info(f'{user} (ID: {user.id}) did not respond to choice prompt in time.')
            await ctx.send(f'{user.mention}, timeout exceeded. Please try again.')
            return ['','','']

        zone_code = match[11]
        print(zone_code)

        return zone_code, match[3].upper(), match[5].upper()

    return ['','','']

async def choose_subzone(ctx, matches_list=None, matches_json=None):
    user = ctx.author
    option_numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "0️⃣"]
    option_message = f'{user.mention}, multiple matches were found. Please select from the following choices:\n'
    option_zone_codes = []
    option_trimmed_list = []
    
    if not matches_json and matches_list:
        matches = matches_list
        for i, option in enumerate(matches):
            if option[5] == option[3] and option[11] not in option_zone_codes:
                option_message += f'{i+1}. County: {option[5]}\n'
                option_trimmed_list.append(option)
            elif option[11] not in option_zone_codes:
                option_message += f'{i+1}. County: {option[5]}, Zone: {option[3]}\n'
                option_trimmed_list.append(option)
            option_zone_codes.append(option[11])

    if not matches_list and matches_json:
        matches = matches_json
        for i, option in enumerate(matches):
            if option['county'] == option['zone']:
                option_message += f"{i+1}. County: {option['county']}\n"
                option_trimmed_list.append(option)
            else:
                option_message += f"{i+1}. County: {option['county']}, Zone: {option['zone']}\n"
                option_trimmed_list.append(option)

    sent_message = await ctx.send(option_message)

    for i in range(len(option_trimmed_list)):
        await sent_message.add_reaction(option_numbers[i])

    def check(reaction, user):
        return user == ctx.author and reaction.message.id == sent_message.id

    try:
        reaction, user = await ctx.bot.wait_for('reaction_add', timeout=60, check=check)
        selected_option_index = option_numbers.index(str(reaction.emoji))
        selected_option = matches[selected_option_index]
        return selected_option

    except asyncio.TimeoutError:
        return ['Timeout']

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
    new_zones = ''

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
    zone_code, zone_name, county = await get_noaa_zone(ctx, county, state)

    if not county:
        return

    if not zone_code:
        logging.info(f'{user} (ID: {user.id}) requested subscription for {county} COUNTY {state} but it could not be found.')
        await ctx.send(f'{user.mention}, failed to retrieve the NOAA zone code for {county} COUNTY, {state}.')
        return

    if zone_code not in subscriptions:
        subscriptions[zone_code] = {
            'zone': zone_name,
            'county': county,
            'state': state,
            'users': [],
            'alerts': []
        }
        new_zone = zone_code
        existing_alerts = []
    else:
        existing_alerts = get_existing_alerts(zone_code)
    
    if user.id in subscriptions[zone_code]['users']:
        logging.info(f'{user} (ID: {user.id}) requested duplicate subscription for {county} COUNTY {state}.')
        await ctx.send(f'{user.mention}, you are already subscribed to alerts for {county} COUNTY, {state}.')
        return

    subscriptions[zone_code]['users'].append(user.id)

    if existing_alerts:
        await alert_user(user, county_state, existing_alerts)
    
    logging.info(f'Subscribing {user} (ID: {user.id}) to alerts for {county} COUNTY, {state}.')
    await ctx.send(f'{user.mention}, you are now subscribed to alerts for {county} COUNTY, {state}.')

    save_subscriptions(subscriptions)
    
    if new_zone:
        await check_weather_alerts_for_single_zone(new_zone, subscriptions[new_zone])

@bot.command()
async def unsubscribe(ctx, *, location=None):
    user = ctx.author

    if location is None:
        subscribed_counties = [subscriptions[county_code]['county'] + ', ' + subscriptions[county_code]['state'] for county_code, data in subscriptions.items() if user.id in data['users']]
        
        for county_code in subscriptions.keys():
            if user.id in subscriptions[county_code]['users']:
                subscriptions[county_code]['users'].remove(user.id)
        
        logging.info(f'Unsubscribing {user} (ID: {user.id}) from all counties.')
        await ctx.send(f'{user.mention}, you have been unsubscribed from all counties.')
        save_subscriptions(subscriptions)
        return

    match = re.match(r'^([\w\s.,/-]+),\s*([\w\s.-]+)$', location)
    
    if not match:
        logging.info(f'Invalid unsubscription request received from from {user} (ID: {user.id}).')
        await ctx.send(f'{user.mention}, please provide a valid location in the format "county, state".')
        return
    
    county = match.group(1).strip().upper()
    state = match.group(2).strip().upper()
    county_state = f'{county}, {state}'
    matching_subscriptions = []
    
    for county_code, data in subscriptions.items():
        if county in data['county'] and data['state'] == state and user.id in data['users']:
            matching_subscriptions.append(data)
            
    if len(matching_subscriptions) > 1:
        match = await choose_subzone(ctx, None, matching_subscriptions)
    else:
        match = matching_subscriptions[0]

    data['users'].remove(user.id)
    logging.info(f'Unsubscribing {user} (ID: {user.id}) from alerts for {county} COUNTY, {state}.')
    await ctx.send(f'{user.mention}, you have been unsubscribed from alerts for {county} COUNTY, {state}.')
    save_subscriptions(subscriptions)
    return

    await ctx.send(f'{user.mention}, you are not currently subscribed to alerts for {county} COUNTY, {state}.')

@bot.command()
async def my_subscriptions(ctx):
    user = ctx.author
    subscribed_counties = [subscriptions[county_code]['county'] + ', ' + subscriptions[county_code]['state'] for county_code, data in subscriptions.items() if user.id in data['users']]
    
    if not subscribed_counties:
        await ctx.send(f'{user.mention}, you are not subscribed to any counties.')
        return
    
    logging.info(f'{user} (ID: {user.id}) requested their list of subscriptions.')
    await ctx.send(f'{user.mention}, you are subscribed to the following counties: {", ".join(subscribed_counties)}')

@tasks.loop(minutes=1)
async def check_weather_alerts():
    for county_code, data in list(subscriptions.items()):
        await check_weather_alerts_for_single_zone(county_code, data)

async def check_weather_alerts_for_single_zone(county_code, data):
    logging.debug(f'Polling NOAA API for Alert Zone {county_code}.')

    if not county_code:
        logging.info(f'County code for {county_state} has been corrupted.')
        return

    response = requests.get(f'https://api.weather.gov/alerts/active?zone={county_code}')

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
        data = remove_existing_alert(data, response_data)
        new_alerts = await add_new_alerts(data, event, headline, description)
        if new_alerts:
            await alert_subscribed_users(county_code, new_alerts)

    subscriptions[county_code] = data
    save_subscriptions(subscriptions)


async def alert_user(user, county_state, alerts):
    county_code = next((county_code for county_code, data in subscriptions.items() if data['county'] + ', ' + data['state'] == county_state), None)

    if county_code is None:
        return
    
    county = subscriptions[county_code]['county']
    state = subscriptions[county_code]['state']
    alert_messages = "\n".join([f'**{event}**\n{headline}\n\n{description}' for event, headline, description in alerts])
    await user.send(f'***!!!!!!!! ALERT FOR {county} COUNTY, {state} !!!!!!!!***\n{alert_messages}')

async def alert_subscribed_users(county_code, new_alerts):
    if county_code not in subscriptions:
        return
    
    user_ids = subscriptions[county_code]['users']
    
    for user_id in user_ids:
        user = await bot.fetch_user(user_id)

        if user:
            await alert_user(user, subscriptions[county_code]['county'] + ', ' + subscriptions[county_code]['state'], new_alerts)

bot.run(TOKEN)
