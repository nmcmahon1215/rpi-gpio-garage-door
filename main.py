import json
from threading import Timer
from time import sleep

import requests
from requests import RequestException

import config
import logging
import os
import sys
import RPi.GPIO as GPIO
import door_state as DOOR_STATE

from flask import Flask, request, Response

app = Flask(__name__)
target_state = None
processing_target = None


@app.route("/status")
def get_status():
    if request is not None and request.args['field'] is not None:
        field_name = str(request.args['field'])
        json_response = {field_name: get_complete_status()[field_name]}
        return json.dumps(json_response)
    else:
        return json.dumps(get_complete_status())


def get_complete_status():
    return {
        "currentState": get_current_state(),
        "targetState": target_state,
        "obstruction": get_obstructions(),
    }


@app.route("/control")
def trigger_door():
    global target_state, processing_target
    if int(request.args["targetState"]) != target_state:
        try:
            GPIO.output(relay_pin, 0)
            sleep(config.get_server_config().get("relay_gpio_delay_ms", 1500) / 1000)
            target_state = int(request.args["targetState"])
        finally:
            GPIO.output(relay_pin, 1)

        Timer(config.get_server_config().get("open_delay", 10), mark_complete, []).start()
        processing_target = target_state
    return Response(status=200)


def mark_complete():
    global processing_target
    last_target = processing_target
    processing_target = None
    if last_target == DOOR_STATE.OPEN:
        sensor_change("update")
    elif last_target == DOOR_STATE.CLOSED and get_current_state() != DOOR_STATE.CLOSED:
        sensor_change("update")


def get_current_state():
    if GPIO.input(sensor_pin):
        if processing_target == DOOR_STATE.CLOSED:
            return DOOR_STATE.CLOSING
        elif processing_target == DOOR_STATE.OPEN:
            return DOOR_STATE.OPENING
        else:
            return DOOR_STATE.OPEN
    else:
        return DOOR_STATE.CLOSED


def sensor_change(pin):
    global target_state

    if processing_target == DOOR_STATE.OPEN:
        # Wait to send the open signal
        return

    sensor_state = GPIO.input(sensor_pin)
    if pin == "retry":
        logging.info("Retrying status update. Door state is " + ("OPEN" if sensor_state else "CLOSED"))
    else:
        logging.info("Sensor change detected. Door state is " + ("OPEN" if sensor_state else "CLOSED"))

    target_state = DOOR_STATE.OPEN if sensor_state else DOOR_STATE.CLOSED
    url = config.get_server_config().get("status_url")
    if url is not None:
        try:
            resp = requests.post(url, data=json.dumps(get_complete_status()))
            resp.raise_for_status()
        except RequestException as e:
            logging.error(e)
            logging.error("Failed to make request: " + url + "\n Retrying in 30 seconds")
            Timer(30.0, sensor_change, ["retry"]).start()

    else:
        logging.error("Status URL not set. Skippin status update.")


def get_obstructions():
    return False


def get_script_path():
    return os.path.dirname(os.path.realpath(sys.argv[0]))


if __name__ == '__main__':
    try:
        GPIO.setmode(GPIO.BOARD)
        app.config['TEMPLATES_AUTO_RELOAD'] = True
        logging.basicConfig(level=logging.INFO, format='%(asctime)s:\t%(levelname)s:\t%(message)s',
                            datefmt='%m/%d/%Y %I:%M:%S %p')
        logging.info("Loading configuration...")
        config.load_server_config(get_script_path() + "/pidoor.conf")
        logging.info("Configuration loaded")

        GPIO.setmode(GPIO.BOARD)
        logging.info("GPIO initialized. Setting up pins.")

        sensor_pin = config.get_server_config().get("sensor_gpio_pin")
        if sensor_pin is not None:
            logging.info("Setting up sensor on GPIO pin " + str(sensor_pin))
            GPIO.setup(sensor_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            GPIO.add_event_detect(sensor_pin, GPIO.BOTH, callback=sensor_change)
            target_state = get_current_state()
        else:
            logging.warn("Sensor pin not defined in configuration. Skipping.")

        relay_pin = config.get_server_config().get("relay_gpio_pin")
        if relay_pin is not None:
            logging.info("Setting up relay on GPIO pin " + str(relay_pin))
            GPIO.setup(relay_pin, GPIO.OUT, initial=1)
        else:
            logging.warn("Relay pin not defined in configuration. Skipping.")

        port_num = config.get_server_config().get('port', 80)
        logging.info("Starting server on port " + str(port_num))

        app.run(port=port_num, host='0.0.0.0')
    finally:
        GPIO.cleanup()
