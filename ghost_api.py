import requests # pip install requests
import jwt	# pip install pyjwt
from datetime import datetime as date
from dotenv import load_dotenv
import os

load_dotenv()

# Url of the ghost blog
URL = os.getenv('URL')

# Ghost Admin API key goes here
key = os.getenv('GHOST_ADMIN_KEY')

# Split the key into ID and SECRET
id, secret = key.split(':')

def deliver_content(slug):
    # Make an authenticated request to get a posts html
    url = '%s/ghost/api/v3/admin/posts/slug/%s/?formats=html' % (URL, slug)
    headers = {'Authorization': 'Ghost {}'.format(create_token())}
    article = requests.get(url, headers=headers).json()['posts'][0]
    return {'content': article['html'], 'excerpt': article['excerpt'], 'title': article['title'], 'origin': '%s/%s' % (URL, slug)}

def create_token():
    iat = int(date.now().timestamp())
    header = {'alg': 'HS256', 'typ': 'JWT', 'kid': id}
    payload = {
        'iat': iat,
        'exp': iat + 5 * 60,
        'aud': '/v3/admin/'
    }
    return jwt.encode(payload, bytes.fromhex(secret), algorithm='HS256', headers=header)

def check_slug_exists(slug):
    return requests.get('%s/%s' % (URL,slug)).status_code == 200