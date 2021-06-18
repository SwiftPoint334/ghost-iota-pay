from flask import Flask, render_template, request, make_response, session
import logging
import secrets
import hashlib
import ghost_api as ghost
from dotenv import load_dotenv
import os
from datetime import timedelta
from flask_socketio import SocketIO
import iota_client
import json
import queue
import time


load_dotenv()

app = Flask(__name__.split('.')[0])

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')

# create web socket for async communication
socketio = SocketIO(app, async_mode='threading')

socket_session_ids = {}

# restrict the access time for the user
# comment out for infinite
app.permanent_session_lifetime = timedelta(hours=int(os.getenv('SESSION_LIFETIME')))


logging.basicConfig(level=logging.DEBUG)
# Set it to you domain
LOG = logging.getLogger("ghost-iota-pay")


# init iota client
iota = iota_client.Client()

# iota address for transfers
iota_address= os.getenv('IOTA_ADDRESS')

# price per content
PRICE = 1000000

# register all paying user token hashes
payed_db= {}


# The node mqtt url
node_url = 'https://chrysalis-nodes.iota.org/' # mainnet if needed

# The queue to store received events
q = queue.Queue()
# queue stop object
STOP = object()

# The IOTA MQTT broker options
broker_options = {
    'automatic_disconnect': True,
    'timeout': 30,
    'use_ws': True,
    'port': 443,
    'max_reconnection_attempts': 5,
}

# create the iota client
client = iota_client.Client(mqtt_broker_options=broker_options)

print(client.get_info())


@app.route('/', methods=["GET"])
def welcome():
    return render_template('welcome.html')

@app.route('/<slug>', methods=["GET"])
def proxy(slug):

    # Check if slug exists and add to db
    if slug not in payed_db.keys():

        if ghost.check_slug_exists(slug):

            payed_db[slug] = set()

            LOG.debug("Added slug %s to db", slug)

        else:

            return make_response('Slug not available')
    

    # Check if user already has cookie and set one 
    if 'iota_ghost_user_token' not in session:
        session['iota_ghost_user_token'] = secrets.token_hex(16)
        return render_template('pay.html')

	
    user_token_hash = hashlib.sha256(session['iota_ghost_user_token'].encode('utf-8')).hexdigest()
    
    if user_token_hash in payed_db[slug]:

        return ghost.deliver_content(slug)

    return render_template('pay.html', user_token_hash = user_token_hash, iota_address = iota_address, slug = slug, price = PRICE )


# socket endpoint to receive payment event
# strangely the dict does not persist the ids
@socketio.on('await_payment')
def await_payment(data):

    user_token_hash = data['user_token_hash']

    socket_session_ids[user_token_hash] = request.sid



@socketio.on('disconnect')
def disconnect():

    print('discon')


def on_mqtt_event(event):
    """Put the received event to queue.
    """
    q.put(event)



def mqtt():
    client.subscribe_topics(['addresses/%s/outputs' % iota_address], on_mqtt_event)
    mqtt_worker()


def mqtt_worker():
    """The worker to process the queued events.
    """
    while True:
        item = q.get(True)
        if item is STOP: break
        event = json.loads(item)

        message = client.get_message_data(json.loads(event['payload'])['messageId'])

        if check_payment(message):
            # this must be easier to access within value transfers
            data = bytes(message['payload']['transaction'][0]['essence']['payload']['indexation'][0]['data']).decode()

            slug = data.split(':')[0]
            user_token_hash = data.split(':')[1]

            payed_db[slug].add(user_token_hash)         

            if user_token_hash in socket_session_ids.keys():

                # emit pamyent received event to the user
                socketio.emit('payment_received', room=socket_session_ids.pop(user_token_hash))

                print('%s bought slug %s' % (user_token_hash, slug))

        q.task_done()


def check_payment(message):

    for output in message['payload']['transaction'][0]['essence']['outputs']:

        if output['signature_locked_single']['address'] == iota_address:

            if output['signature_locked_single']['amount'] >= PRICE:

                return True

    return False

if __name__ == '__main__':
    try:

        # sadly this all has to run in the same script
        socketio.start_background_task(mqtt)
        socketio.run(app)

    except KeyboardInterrupt:
        print('Stopping')
        q.put(STOP)
        client.disconnect()
        q.queue.clear()
        exit()