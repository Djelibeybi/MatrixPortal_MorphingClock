"""
MatrixPortal S3 Morphing Clock for CiruitPython 9.2.

Updated from https://github.com/brianmwhite/MatrixPortal_MorphingClock.

Digit morphing code ported from https://www.instructables.com/Morphing-Digital-Clock/
https://github.com/hwiguna/HariFun_166_Morphing_Clock

Some code taken from
https://github.com/adafruit/Adafruit_Learning_System_Guides/blob/main/Metro_Matrix_Clock/code.py

SPDX-FileCopyrightText: 2020 John Park for Adafruit Industries
SPDX-License-Identifier: MIT
"""

import time

import analogio
import board
import displayio
import terminalio
from adafruit_bitmap_font import bitmap_font
from adafruit_datetime import datetime
from adafruit_display_text import label
from adafruit_ds3231 import DS3231
from adafruit_matrixportal.matrix import Matrix
from adafruit_matrixportal.network import Network
from adafruit_minimqtt.adafruit_minimqtt import MQTT, MMQTTException
from adafruit_ntp import NTP
from adafruit_sht4x import SHT4x
from framebufferio import FramebufferDisplay

from digit import Digit


class MatrixPortalError(Exception):
    """Custom error class for MatrixPortal."""

try:
    from secrets import secrets
except ImportError as error:
    raise MatrixPortalError("Missing secrets.py.") from error


DEBUG = False
DARKEST_COLOR = 255
BRIGHTEST_COLOR = 16711680

TEMPERATURE_INTERVAL_SECONDS = 60
BRIGHTNESS_INTERVAL_SECONDS = 1

PHOTOCELL_MIN_VALUE = 0
PHOTOCELL_MAX_VALUE = 15000

GRADIENT_PALETTE = [
    1812, 1558, 1560, 1563, 1565, 1567, 1570, 1572, 1575, 1577, 1579, 1582, 1584,
    1587, 1589, 1335, 1338, 1340, 1342, 1345, 1347, 1350, 1352, 1354, 1357, 1359,
    1362, 1364, 1366, 1113, 1115, 1117, 1120, 1122, 1125, 1127, 1129, 1132, 1134,
    1137, 1139, 1141, 1144, 890, 892, 895, 897, 900, 902, 904, 907, 909, 911, 914,
    916, 919, 921, 667, 670, 672, 675, 677, 679, 682, 684, 686, 689, 691, 694, 696,
    698, 445, 447, 450, 452, 454, 457, 459, 461, 464, 466, 469, 471, 473, 476, 222,
    225, 227, 229, 232, 234, 236, 239, 241, 244, 246, 248, 251, 253, 255
]

network = Network(status_neopixel=board.NEOPIXEL, debug=True)
network.connect(max_attempts=2)

matrix = Matrix(bit_depth=4)
display: FramebufferDisplay = matrix.display

ds3231 = DS3231(board.I2C())
sht4x = SHT4x(board.I2C())
photocell = analogio.AnalogIn(board.A4)

if ds3231.datetime.tm_year == 2000:
    print("Setting RTC using NTP")
    ntp = NTP(socketpool=network._wifi.pool, server=secrets["ntp_server"], tz_offset=secrets["tz_offset"])
    ds3231.datetime = ntp.datetime

mqtt = MQTT(
    broker=secrets["mqtt_host"],
    port=secrets["mqtt_port"],
    username=secrets["mqtt_username"],
    password=secrets["mqtt_password"],
    client_id=secrets["mqtt_client_id"],
    socket_pool=wifi.pool,
)

previous_epoch = 0
previous_date = None
previous_hour = 0
previous_minute = 0
previous_second = 0

group = displayio.Group()
bitmap = displayio.Bitmap(64, 32, 4)
color = displayio.Palette(color_count=3)
bg_sprite = displayio.TileGrid(bitmap=bitmap, pixel_shader=color)
group.append(bg_sprite)
display.root_group = group


def set_color_bright():
    """Set bright color scheme."""
    global color
    color[0] = 0x000000  # black background
    color[1] = BRIGHTEST_COLOR
    color[2] = BRIGHTEST_COLOR


def set_color_dark():
    """Set dark color scheme."""
    global color
    color[0] = 0x000000  # black background
    color[1] = DARKEST_COLOR
    color[2] = DARKEST_COLOR


set_color_bright()


if not DEBUG:
    font = bitmap_font.load_font("/lemon.bdf")
else:
    font = terminalio.FONT

date_text_area = label.Label(font, text="", color=color[1])
date_text_area.x = 6
date_text_area.y = 19
group.append(date_text_area)

temp_text_area = label.Label(font, text="", color=color[1])
temp_text_area.x = 11
temp_text_area.y = 28
group.append(temp_text_area)

digit0 = Digit(d=group, b=bitmap, value=0, xo=63 - 1 - 9 * 1, yo=32 - 15 - 1, color=1)
digit1 = Digit(d=group, b=bitmap, value=0, xo=63 - 1 - 9 * 2, yo=32 - 15 - 1, color=1)
digit2 = Digit(d=group, b=bitmap, value=0, xo=63 - 4 - 9 * 3, yo=32 - 15 - 1, color=1)
digit3 = Digit(d=group, b=bitmap, value=0, xo=63 - 4 - 9 * 4, yo=32 - 15 - 1, color=1)
digit4 = Digit(d=group, b=bitmap, value=0, xo=63 - 7 - 9 * 5, yo=32 - 15 - 1, color=1)
digit5 = Digit(d=group, b=bitmap, value=0, xo=63 - 7 - 9 * 6, yo=32 - 15 - 1, color=1)

digit1.DrawColon(1)
digit3.DrawColon(1)


def calculate_color_from_brightness(pc_val: int) -> int:
    """
    Calculate the color based on photocell_value from the gradient palette.

    Position 0 in the gradient corresponds to the photocell min value,
    and the last value in the gradient corresponds to the photocell max value.
    """
    normalized_value = (pc_val - PHOTOCELL_MIN_VALUE) / (PHOTOCELL_MAX_VALUE - PHOTOCELL_MIN_VALUE)
    normalized_value = max(0, min(1, normalized_value))
    index = int(normalized_value * (len(GRADIENT_PALETTE) - 1))
    return GRADIENT_PALETTE[index]


def update_time():
    """Update the time on the display."""
    current_time = ds3231.datetime
    epoch = time.mktime(current_time)
    current_date = datetime.fromtimestamp(epoch)

    global previous_date
    global previous_epoch
    global previous_hour
    global previous_minute
    global previous_second

    if epoch != previous_epoch:
        hh = current_time.tm_hour
        # if hh > 12:
        #     hh = hh - 12
        mm = current_time.tm_min
        ss = current_time.tm_sec
        if previous_epoch == 0:  # // If we didn't have a previous time. Just draw it without morphing.
            digit0.Draw(int(ss % 10))
            digit1.Draw(int(ss / 10))
            digit2.Draw(int(mm % 10))
            digit3.Draw(int(mm / 10))
            digit4.Draw(int(hh % 10))
            digit5.Draw(int(hh / 10))

            date_text_area.text = current_date.ctime()[:10]
        else:
            if ss != previous_second:
                s0 = int(ss % 10)
                s1 = int(ss / 10)
                if s0 != digit0.Value():
                    digit0.Morph(s0)
                if s1 != digit1.Value():
                    digit1.Morph(s1)
                previous_second = ss

            if mm != previous_minute:
                m0 = int(mm % 10)
                m1 = int(mm / 10)
                if m0 != digit2.Value():
                    digit2.Morph(m0)
                if m1 != digit3.Value():
                    digit3.Morph(m1)
                previous_minute = mm

            if hh != previous_hour:
                h0 = int(hh % 10)
                h1 = int(hh / 10)
                if h0 != digit4.Value():
                    digit4.Morph(h0)
                if h1 != digit5.Value():
                    digit5.Morph(h1)
                previous_hour = hh

            if (
                current_date.month != previous_date.month
                or current_date.day != previous_date.day
                or current_date.year != previous_date.year
            ):
                print(f"Changing date to {current_date.isoformat()[:10]}")
                date_text_area.text = current_date.ctime()[:10]

        previous_epoch = epoch
        previous_date = current_date


def subscribe():
    """Subscribe to MQTT topic."""
    try:
        mqtt.connect()
        mqtt.is_connected()
        mqtt.subscribe(f"{secrets['mqtt_topic']}/#")
        print("MQTT is connected.")
    except MMQTTException:
        pass


subscribe()

last_temp_check = None
last_brightness_check = None

while True:
    if last_brightness_check is None or time.monotonic() > last_brightness_check + BRIGHTNESS_INTERVAL_SECONDS:
        color[0] = 0x000000
        color[1] = calculate_color_from_brightness(photocell.value)
        color[2] = color[1]

        print(f"Color: {color[1]} for {photocell.value}")
        last_brightness_check = time.monotonic()

    temp_text_area.color = color[2]
    date_text_area.color = color[2]

    if last_temp_check is None or time.monotonic() > last_temp_check + TEMPERATURE_INTERVAL_SECONDS:
        currentTemperature = sht4x.temperature
        currentHumidity = sht4x.relative_humidity
        temp_text_area.text = f"{round(currentTemperature)}°  {round(currentHumidity)}%"

        try:
            mqtt.is_connected()
            mqtt.publish(f"{secrets['mqtt_topic']}/temperature", currentTemperature)
            mqtt.publish(f"{secrets['mqtt_topic']}/humidity", currentHumidity)
            mqtt.publish(f"{secrets['mqtt_topic']}/photocell", photocell.value)

        except (MMQTTException, RuntimeError, ConnectionError) as error:
            time.sleep(5)
            print("MQTT error: ", error)
            try:
                network.connect()
                mqtt.reconnect()
            except (MMQTTException, RuntimeError, ConnectionError) as ex:
                print("MQTT error: ", ex)

        last_temp_check = time.monotonic()

    update_time()
    time.sleep(0.01)
