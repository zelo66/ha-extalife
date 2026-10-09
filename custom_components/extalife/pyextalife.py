""" ExtaLife JSON API wrapper library. Enables device control, discovery and status fetching from EFC-01 controller """

import asyncio
import json
import logging
import os
import re
import socket
import sys
import time
from contextlib import suppress
from asyncio import (
    CancelledError as AsyncCancelledError,
    Lock,
    StreamReader,
    StreamWriter,
    Task,
    TimeoutError as AsyncTimeoutError,
)
from asyncio.events import AbstractEventLoop
from datetime import (
    datetime,
)
from enum import (
    auto,
    Flag,
    IntEnum,
    StrEnum
)
from typing import (
    Any,
)
from collections.abc import Awaitable, Callable

_LOGGER = logging.getLogger(__name__)

# controller info
PRODUCT_MANUFACTURER = "ZAMEL"
PRODUCT_SERIES_EXTA_LIFE = "Exta Life"
PRODUCT_SERIES_EXTA_FREE = "Exta Free"

ExtaLifeResponseType = "ExtaLifeResponse"
ExtaLifeActionType = "ExtaLifeAction"
ExtaLifeErrorType = "ExtaLifeError"
ExtaLifeConnType = "ExtaLifeConn"

type ExtaLifeData = dict[str, Any]
type ExtaLifeDataList = list[ExtaLifeData]


class ExtaLifeEvent(IntEnum):
    CONNECTED = 1,
    DISCONNECTED = 2,
    NOTIFICATION = 3,


class ExtaLifeDeviceModelName(StrEnum):
    # Exta Life
    EFC01 = "EFC-01"
    RNK22 = "RNK-22"
    RNK22_TEMP_SENSOR = "RNK-22 temperature sensor"
    RNK24 = "RNK-24"
    RNK24_TEMP_SENSOR = "RNK-24 temperature sensor"
    P4572 = "P-457/2"
    P4574 = "P-457/4"
    P4578 = "P-457/8"
    P45736 = "P457/36"
    LEDIX_P260 = "ledix touch control P260"
    ROP21 = "ROP-21"
    ROP22 = "ROP-22"
    SRP22 = "SRP-22"
    RDP21 = "RDP-21"
    GKN01 = "GKN-01"
    ROP27 = "ROP-27"
    RGT01 = "RGT-01"
    RNM24 = "RNM-24"
    RNP21 = "RNP-21"
    RNP22 = "RNP-22"
    RCT21 = "RCT-21"
    RCT22 = "RCT-22"
    ROG21 = "ROG-21"
    ROM22 = "ROM-22"
    ROM24 = "ROM-24"
    SRM22 = "SRM-22"
    SLR21 = "SLR-21"
    SLR22 = "SLR-22"
    SLN21 = "SLN-21"
    SLN22 = "SLN-22"
    RCM21 = "RCM-21"
    MEM21 = "MEM-21"
    RCR21 = "RCR-21"
    RCZ21 = "RCZ-21"
    RCW21 = "RCW-21"
    SLM21 = "SLM-21"
    SLM22 = "SLM-22"
    RCK21 = "RCK-21"
    ROB21 = "ROB-21"
    REP21 = "REP-21"
    P501 = "P-501"
    P520 = "P-520"
    P521L = "P-521L"
    BULIK_DRS985 = "bulik DRS-985"

    # Exta Free
    ROP01 = "ROP-01"
    ROP02 = "ROP-02"
    ROM01 = "ROM-01"
    ROM10 = "ROM-10"
    ROP05 = "ROP-05"
    ROP06 = "ROP-06"
    ROP07 = "ROP-07"
    RWG01 = "RWG-01"
    ROB01 = "ROB-01"
    SRP02 = "SRP-02"
    RDP01 = "RDP-01"
    RDP02 = "RDP-02"
    RDP11 = "RDP-11"
    SRP03 = "SRP-03"


class ExtaLifeDeviceModel(IntEnum):
    RNK22 = 1
    RNK22_TEMP_SENSOR = 2
    RNK24 = 3
    RNK24_TEMP_SENSOR = 4
    P4572 = 5
    P4574 = 6
    P4578 = 7
    P45736 = 8
    LEDIX_P260 = 9
    ROP21 = 10
    ROP22 = 11
    SRP22 = 12
    RDP21 = 13
    GKN01 = 14
    ROP27 = 15
    RGT01 = 16
    RNM24 = 17
    RNP21 = 18
    RNP22 = 19
    RCT21 = 20
    RCT22 = 21
    ROG21 = 22
    ROM22 = 23
    ROM24 = 24
    SRM22 = 25
    SLR21 = 26
    SLR22 = 27
    RCM21 = 28
    MEM21 = 35
    RCR21 = 41
    RCZ21 = 42
    SLN21 = 45
    SLN22 = 46
    RCK21 = 47
    ROB21 = 48
    P501 = 51
    P520 = 52
    P521L = 53
    RCW21 = 131
    REP21 = 237
    BULIK_DRS985 = 238
    EFC01 = 252

    EXTA_FREE_FIRST = 300
    ROP01 = 326
    ROP02 = 327
    ROM01 = 328
    ROM10 = 329
    ROP05 = 330
    ROP06 = 331
    ROP07 = 332
    RWG01 = 333
    ROB01 = 334
    SRP02 = 335
    RDP01 = 336
    RDP02 = 337
    RDP11 = 338
    SRP03 = 339

class ExtaGateChannelType(IntEnum):
    GATE = 0
    TILT_GATE = 1,
    WICKET = 2,
    MONO_SWITCH = 3

class ExtaGateChannelState(IntEnum):
    NONE = 0
    OPEN = 1
    PARTIALLY_OPEN = 2
    CLOSED = 3

class ExtaLifeAction(StrEnum):
    # Exta Life Actions
    EXTA_LIFE_TURN_ON = "TURN_ON"
    EXTA_LIFE_TURN_OFF = "TURN_OFF"
    EXTA_LIFE_SET_BRI = "SET_BRIGHTNESS"
    EXTA_LIFE_SET_RGB = "SET_COLOR"
    EXTA_LIFE_SET_POS = "SET_POSITION"
    EXTA_LIFE_GATE_POS = "SET_GATE_POSITION"
    EXTA_LIFE_SET_TMP = "SET_TEMPERATURE"
    EXTA_LIFE_STOP = "STOP"
    EXTA_LIFE_OPEN = "UP"
    EXTA_LIFE_CLOSE = "DOWN"
    EXTA_LIFE_SET_SLR_MODE = "SET_MODE"
    EXTA_LIFE_SET_RGT_MODE_MANUAL = "RGT_SET_MODE_MANUAL"
    EXTA_LIFE_SET_RGT_MODE_AUTO = "RGT_SET_MODE_AUTO"

    # Exta Free Actions
    EXTA_FREE_TURN_ON_PRESS = "TURN_ON_PRESS"
    EXTA_FREE_TURN_ON_RELEASE = "TURN_ON_RELEASE"
    EXTA_FREE_TURN_OFF_PRESS = "TURN_OFF_PRESS"
    EXTA_FREE_TURN_OFF_RELEASE = "TURN_OFF_RELEASE"
    EXTA_FREE_UP_PRESS = "UP_PRESS"
    EXTA_FREE_UP_RELEASE = "UP_RELEASE"
    EXTA_FREE_DOWN_PRESS = "DOWN_PRESS"
    EXTA_FREE_DOWN_RELEASE = "DOWN_RELEASE"
    EXTA_FREE_BRIGHT_UP_PRESS = "BRIGHT_UP_PRESS"
    EXTA_FREE_BRIGHT_UP_RELEASE = "BRIGHT_UP_RELEASE"
    EXTA_FREE_BRIGHT_DOWN_PRESS = "BRIGHT_DOWN_PRESS"
    EXTA_FREE_BRIGHT_DOWN_RELEASE = "BRIGHT_DOWN_RELEASE"


class ExtaLifeMap:
    # device types string mapping
    __MAP_TYPE_TO_MODEL_NAME: dict[ExtaLifeDeviceModel, ExtaLifeDeviceModelName] = {
        ExtaLifeDeviceModel.EFC01: ExtaLifeDeviceModelName.EFC01,
        ExtaLifeDeviceModel.RNK22: ExtaLifeDeviceModelName.RNK22,
        ExtaLifeDeviceModel.RNK22_TEMP_SENSOR: ExtaLifeDeviceModelName.RNK22_TEMP_SENSOR,
        ExtaLifeDeviceModel.RNK24: ExtaLifeDeviceModelName.RNK24,
        ExtaLifeDeviceModel.RNK24_TEMP_SENSOR: ExtaLifeDeviceModelName.RNK24_TEMP_SENSOR,
        ExtaLifeDeviceModel.P4572: ExtaLifeDeviceModelName.P4572,
        ExtaLifeDeviceModel.P4574: ExtaLifeDeviceModelName.P4574,
        ExtaLifeDeviceModel.P4578: ExtaLifeDeviceModelName.P4578,
        ExtaLifeDeviceModel.P45736: ExtaLifeDeviceModelName.P45736,
        ExtaLifeDeviceModel.LEDIX_P260: ExtaLifeDeviceModelName.LEDIX_P260,
        ExtaLifeDeviceModel.ROP21: ExtaLifeDeviceModelName.ROP21,
        ExtaLifeDeviceModel.ROP22: ExtaLifeDeviceModelName.ROP22,
        ExtaLifeDeviceModel.SRP22: ExtaLifeDeviceModelName.SRP22,
        ExtaLifeDeviceModel.RDP21: ExtaLifeDeviceModelName.RDP21,
        ExtaLifeDeviceModel.GKN01: ExtaLifeDeviceModelName.GKN01,
        ExtaLifeDeviceModel.ROP27: ExtaLifeDeviceModelName.ROP27,
        ExtaLifeDeviceModel.RGT01: ExtaLifeDeviceModelName.RGT01,
        ExtaLifeDeviceModel.RNM24: ExtaLifeDeviceModelName.RNM24,
        ExtaLifeDeviceModel.RNP21: ExtaLifeDeviceModelName.RNP21,
        ExtaLifeDeviceModel.RNP22: ExtaLifeDeviceModelName.RNP22,
        ExtaLifeDeviceModel.RCT21: ExtaLifeDeviceModelName.RCT21,
        ExtaLifeDeviceModel.RCT22: ExtaLifeDeviceModelName.RCT22,
        ExtaLifeDeviceModel.ROG21: ExtaLifeDeviceModelName.ROG21,
        ExtaLifeDeviceModel.ROM22: ExtaLifeDeviceModelName.ROM22,
        ExtaLifeDeviceModel.ROM24: ExtaLifeDeviceModelName.ROM24,
        ExtaLifeDeviceModel.SRM22: ExtaLifeDeviceModelName.SRM22,
        ExtaLifeDeviceModel.SLR21: ExtaLifeDeviceModelName.SLR21,
        ExtaLifeDeviceModel.SLR22: ExtaLifeDeviceModelName.SLR22,
        ExtaLifeDeviceModel.RCM21: ExtaLifeDeviceModelName.RCM21,
        ExtaLifeDeviceModel.MEM21: ExtaLifeDeviceModelName.MEM21,
        ExtaLifeDeviceModel.RCR21: ExtaLifeDeviceModelName.RCR21,
        ExtaLifeDeviceModel.RCZ21: ExtaLifeDeviceModelName.RCZ21,
        ExtaLifeDeviceModel.SLN21: ExtaLifeDeviceModelName.SLN21,
        ExtaLifeDeviceModel.SLN22: ExtaLifeDeviceModelName.SLN22,
        ExtaLifeDeviceModel.RCK21: ExtaLifeDeviceModelName.RCK21,
        ExtaLifeDeviceModel.ROB21: ExtaLifeDeviceModelName.ROB21,
        ExtaLifeDeviceModel.P501: ExtaLifeDeviceModelName.P501,
        ExtaLifeDeviceModel.P520: ExtaLifeDeviceModelName.P520,
        ExtaLifeDeviceModel.P521L: ExtaLifeDeviceModelName.P521L,
        ExtaLifeDeviceModel.RCW21: ExtaLifeDeviceModelName.RCW21,
        ExtaLifeDeviceModel.REP21: ExtaLifeDeviceModelName.REP21,
        ExtaLifeDeviceModel.BULIK_DRS985: ExtaLifeDeviceModelName.BULIK_DRS985,

        # Exta Free
        ExtaLifeDeviceModel.ROP01: ExtaLifeDeviceModelName.ROP01,
        ExtaLifeDeviceModel.ROP02: ExtaLifeDeviceModelName.ROP02,
        ExtaLifeDeviceModel.ROM01: ExtaLifeDeviceModelName.ROM01,
        ExtaLifeDeviceModel.ROM10: ExtaLifeDeviceModelName.ROM10,
        ExtaLifeDeviceModel.ROP05: ExtaLifeDeviceModelName.ROP05,
        ExtaLifeDeviceModel.ROP06: ExtaLifeDeviceModelName.ROP06,
        ExtaLifeDeviceModel.ROP07: ExtaLifeDeviceModelName.ROP07,
        ExtaLifeDeviceModel.RWG01: ExtaLifeDeviceModelName.RWG01,
        ExtaLifeDeviceModel.ROB01: ExtaLifeDeviceModelName.ROB01,
        ExtaLifeDeviceModel.SRP02: ExtaLifeDeviceModelName.SRP02,
        ExtaLifeDeviceModel.RDP01: ExtaLifeDeviceModelName.RDP01,
        ExtaLifeDeviceModel.RDP02: ExtaLifeDeviceModelName.RDP02,
        ExtaLifeDeviceModel.RDP11: ExtaLifeDeviceModelName.RDP11,
        ExtaLifeDeviceModel.SRP03: ExtaLifeDeviceModelName.SRP03,
    }

    __MAP_MODEL_NAME_TO_TYPE: dict[ExtaLifeDeviceModelName, ExtaLifeDeviceModel] = {
        v: k for k, v in __MAP_TYPE_TO_MODEL_NAME.items()
    }

    __MAP_ACTION_TO_STATE: dict = {

        # Exta Life:
        ExtaLifeAction.EXTA_LIFE_TURN_ON: 1,
        ExtaLifeAction.EXTA_LIFE_TURN_OFF: 0,
        ExtaLifeAction.EXTA_LIFE_OPEN: 1,
        ExtaLifeAction.EXTA_LIFE_CLOSE: 0,
        ExtaLifeAction.EXTA_LIFE_STOP: 2,
        ExtaLifeAction.EXTA_LIFE_SET_POS: None,
        ExtaLifeAction.EXTA_LIFE_GATE_POS: 1,
        ExtaLifeAction.EXTA_LIFE_SET_RGT_MODE_AUTO: 0,
        ExtaLifeAction.EXTA_LIFE_SET_RGT_MODE_MANUAL: 1,
        ExtaLifeAction.EXTA_LIFE_SET_TMP: 1,

        # Exta Free:
        ExtaLifeAction.EXTA_FREE_TURN_ON_PRESS: 1,
        ExtaLifeAction.EXTA_FREE_TURN_ON_RELEASE: 2,
        ExtaLifeAction.EXTA_FREE_TURN_OFF_PRESS: 3,
        ExtaLifeAction.EXTA_FREE_TURN_OFF_RELEASE: 4,
        ExtaLifeAction.EXTA_FREE_UP_PRESS: 1,
        ExtaLifeAction.EXTA_FREE_UP_RELEASE: 2,
        ExtaLifeAction.EXTA_FREE_DOWN_PRESS: 3,
        ExtaLifeAction.EXTA_FREE_DOWN_RELEASE: 4,
        ExtaLifeAction.EXTA_FREE_BRIGHT_UP_PRESS: 1,
        ExtaLifeAction.EXTA_FREE_BRIGHT_UP_RELEASE: 2,
        ExtaLifeAction.EXTA_FREE_BRIGHT_DOWN_PRESS: 3,
        ExtaLifeAction.EXTA_FREE_BRIGHT_DOWN_RELEASE: 4,
    }

    @classmethod
    def type_to_model_name(cls, device_type: ExtaLifeDeviceModel) -> ExtaLifeDeviceModelName:

        if device_type in cls.__MAP_TYPE_TO_MODEL_NAME:
            return cls.__MAP_TYPE_TO_MODEL_NAME.get(device_type)

        return ExtaLifeDeviceModelName(f"unknown device model ({device_type})")

    @classmethod
    def model_name_to_type(cls, model_name: ExtaLifeDeviceModelName) -> ExtaLifeDeviceModel:

        if model_name in cls.__MAP_MODEL_NAME_TO_TYPE:
            return cls.__MAP_MODEL_NAME_TO_TYPE.get(model_name)

        return ExtaLifeDeviceModel(0)

    @classmethod
    def action_to_state(cls, action: ExtaLifeActionType) -> int:

        return cls.__MAP_ACTION_TO_STATE.get(action)


class ExtaLifeCmd(IntEnum):
    """ Supported Exta Life controller commands"""

    NOOP = 0
    LOGIN = 1
    ACTIVATE_SCENE = 44
    CONTROL_DEVICE = 20
    DOWNLOAD_BACKUP = 500
    FETCH_EXTA_FREE = 203
    FETCH_NETWORK_SETTINGS = 102
    FETCH_RECEIVERS = 37
    FETCH_RECEIVER_CONFIG = 25
    FETCH_RECEIVER_CONFIG_DETAILS = 27
    FETCH_SENSORS = 38
    FETCH_TRANSMITTERS = 39
    GET_EFC_CONFIG_DETAILS = 154
    RESTART = 150
    CHECK_VERSION = 151
    UPDATE_CONTROLLER = 152
    UPDATE_RECEIVERS = 65


class ExtaLifeCmdErrorCode(IntEnum):
    ACCOUNT_ALREADY_EXISTS = -67
    ACTIVATE_INVALID_PARAMETERS = -50
    BATTERY_DEVICE_STANDBY = -40
    CAN_NOT_RESTORE_USER = -22
    CLOUD_ERROR_LOCAL_ONLY = -71
    CLOUD_IS_DISABLED = -34
    CLOUD_TOO_MUCH_REQUEST = -60
    CONFIG_EXISTS = -17
    CONNECTION_INVALID = 0
    DEVICE_ALREADY_ADDED = -16
    DEVICE_CALIBRATION_INVALID = -36
    DEVICE_CONFIG_DO_NOT_EXISTS = -35
    DEVICE_NOT_RESPONDING = -13
    DEVICE_NOT_AVAILABLE = -41
    DEVICE_POSITION_INVALID = -37
    DEVICE_REMOTE_EXISTS = -38
    DISCOVERY_IN_PROGRESS = -19
    EMAIL_ALREADY_SEND = -66
    EMAIL_NOT_EXISTS = -69
    EXCEEDED_LIMIT_PASSWORD_RESET = -68
    FILE_END_OF_FILE = -33
    FILE_INVALID_READ_DATA = -32
    FILE_IS_CORRUPTED = -30
    FILE_IS_TO_BIG = -29
    FILE_NO_FOUND = -28
    FILE_READ_MORE_DATA = -31
    INVALID_CONFIG = -12
    INVALID_DATA = -10
    INVALID_LOG_PASS = -2
    INVALID_OLD_PASSWORD = -8
    INVALID_PERMISSIONS = -7
    INVALID_USER = -6
    MAX_COUNT = -4
    NO_SERVER_CONNECTION = -24
    NO_SUCH_CHANNEL = -11
    NO_SUCH_DATA = -14
    NO_SUCH_DEVICE = -9
    NO_SUCH_USER = -5
    NO_VALID_LIST = 3
    OUT_OF_MEMORY = -101
    OUT_OF_MEMORY_SERIALIZE_JSON = -102
    PASSWORD_EXIST = -23
    RESULT_EXCEPTION_CLOUD_ERROR_FROM_SERVER = -61
    RESULT_EXCEPTION_CLOUD_OBJECT_UNDEFINED = -62
    RESULT_EXCEPTION_NULL_POINTER = -100
    SCENE_TURNED_OFF = -15
    SD_CARD_BUSY = -27
    SERVER_CLOSE_CONNECTION = 400
    SESSION_INVALID = -1
    SIGNATURE_ERROR = 4
    TIMEOUT_CONNECTION_CONTROLLER_CLOUD = -70
    UNDEFINED_PHONE_ID = -63
    UNKNOWN = 1
    UNSUPPORTED_OPERATION = 2
    UPDATE_IN_PROGRESS = -18
    UPLOAD_INIT_FAIL = -21
    UPLOAD_IN_PROGRESS = -20
    USERS_LIMIT = -200
    USER_ALREADY_EXISTS = -3
    WEB_DOWNLOAD_PROGRESS_FAIL = -25
    WEB_SERVER_FILE_NOT_EXIST = -26
    SUCCESS = 0xFFFF


class ExtaLifeResponseStatus(StrEnum):
    SUCCESS = "success"
    SEARCHING = "searching"
    FAILURE = "failure"
    PARTIAL = "partial"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"
    VALIDATION = "validation"
    PROGRESS = "progress"


# Exta Life devices
DEVICE_ARR_SENS_TEMP = [
    ExtaLifeDeviceModel.RNK22_TEMP_SENSOR,
    ExtaLifeDeviceModel.RNK24_TEMP_SENSOR,
    ExtaLifeDeviceModel.RCT21,
    ExtaLifeDeviceModel.RCT22
]

DEVICE_ARR_SENS_LIGHT = []
DEVICE_ARR_SENS_HUMID = []
DEVICE_ARR_SENS_PRESSURE = []

DEVICE_ARR_SENS_WIND = [
    ExtaLifeDeviceModel.RCW21
]

DEVICE_ARR_SENS_MULTI = [
    ExtaLifeDeviceModel.RCM21
]

DEVICE_ARR_SENS_WATER = [
    ExtaLifeDeviceModel.RCZ21
]

DEVICE_ARR_SENS_MOTION = [
    ExtaLifeDeviceModel.RCR21
]

DEVICE_ARR_SENS_OPEN_CLOSE = [
    ExtaLifeDeviceModel.RCK21
]

DEVICE_ARR_SENS_ENERGY_METER = [
    ExtaLifeDeviceModel.MEM21
]

DEVICE_ARR_SENS_GATE_CONTROLLER = [
    ExtaLifeDeviceModel.ROB21
]

DEVICE_ARR_SWITCH = [
    ExtaLifeDeviceModel.ROP21,
    ExtaLifeDeviceModel.ROP22,
    ExtaLifeDeviceModel.ROG21,
    ExtaLifeDeviceModel.ROM22,
    ExtaLifeDeviceModel.ROM24
]
DEVICE_ARR_COVER = [
    ExtaLifeDeviceModel.SRP22,
    ExtaLifeDeviceModel.SRM22
]
DEVICE_ARR_LIGHT = [
    ExtaLifeDeviceModel.RDP21,
    ExtaLifeDeviceModel.SLR21,
    ExtaLifeDeviceModel.SLN21,
    ExtaLifeDeviceModel.SLR22,
    ExtaLifeDeviceModel.SLN22
]

DEVICE_ARR_LIGHT_RGB = []  # RGB only

DEVICE_ARR_LIGHT_RGBW = [
    ExtaLifeDeviceModel.SLR22,
    ExtaLifeDeviceModel.SLN22
]

DEVICE_ARR_LIGHT_EFFECT = [
    ExtaLifeDeviceModel.SLR22,
    ExtaLifeDeviceModel.SLN22
]

DEVICE_ARR_CLIMATE = [
    ExtaLifeDeviceModel.RGT01
]

DEVICE_ARR_REPEATER = [
    ExtaLifeDeviceModel.REP21
]

DEVICE_ARR_TRANS_REMOTE = [
    ExtaLifeDeviceModel.P4572,
    ExtaLifeDeviceModel.P4574,
    ExtaLifeDeviceModel.P4578,
    ExtaLifeDeviceModel.P45736,
    ExtaLifeDeviceModel.P501,
    ExtaLifeDeviceModel.P520,
    ExtaLifeDeviceModel.P521L
]

DEVICE_ARR_TRANS_NORMAL_BATTERY = [
    ExtaLifeDeviceModel.RNK22,
    ExtaLifeDeviceModel.RNK24,
    ExtaLifeDeviceModel.RNP22
]

DEVICE_ARR_TRANS_NORMAL_MAINS = [
    ExtaLifeDeviceModel.RNM24,
    ExtaLifeDeviceModel.RNP21
]

# Exta Free devices
DEVICE_ARR_EXTA_FREE_RECEIVER = [
    80
]

DEVICE_ARR_EXTA_FREE_SWITCH = [
    ExtaLifeDeviceModel.ROP01,
    ExtaLifeDeviceModel.ROP02,
    ExtaLifeDeviceModel.ROM01,
    ExtaLifeDeviceModel.ROM10,
    ExtaLifeDeviceModel.ROP05,
    ExtaLifeDeviceModel.ROP06,
    ExtaLifeDeviceModel.ROP07,
    ExtaLifeDeviceModel.RWG01,
    ExtaLifeDeviceModel.ROB01,
]

DEVICE_ARR_EXTA_FREE_COVER = [
    ExtaLifeDeviceModel.SRP02,
    ExtaLifeDeviceModel.SRP03
]

DEVICE_ARR_EXTA_FREE_LIGHT = [
    ExtaLifeDeviceModel.RDP01,
    ExtaLifeDeviceModel.RDP02
]

DEVICE_ARR_EXTA_FREE_RGB = [
    ExtaLifeDeviceModel.RDP11
]

DEVICE_ARR_ALL_EXTA_FREE_SWITCH = [*DEVICE_ARR_EXTA_FREE_SWITCH]
DEVICE_ARR_ALL_EXTA_FREE_LIGHT = [*DEVICE_ARR_EXTA_FREE_LIGHT, *DEVICE_ARR_EXTA_FREE_RGB]
DEVICE_ARR_ALL_EXTA_FREE_COVER = [*DEVICE_ARR_EXTA_FREE_COVER]

# union of all subtypes
DEVICE_ARR_ALL_SWITCH = [
    *DEVICE_ARR_SWITCH,
    *DEVICE_ARR_ALL_EXTA_FREE_SWITCH
]

DEVICE_ARR_ALL_LIGHT = [
    *DEVICE_ARR_LIGHT,
    *DEVICE_ARR_LIGHT_RGB,
    *DEVICE_ARR_LIGHT_RGBW,
    *DEVICE_ARR_ALL_EXTA_FREE_LIGHT,
]

DEVICE_ARR_ALL_COVER = [
    *DEVICE_ARR_COVER,
    *DEVICE_ARR_SENS_GATE_CONTROLLER,
    *DEVICE_ARR_ALL_EXTA_FREE_COVER
]

DEVICE_ARR_ALL_CLIMATE = [
    *DEVICE_ARR_CLIMATE
]

DEVICE_ARR_ALL_TRANSMITTER = [
    *DEVICE_ARR_TRANS_REMOTE,
    *DEVICE_ARR_TRANS_NORMAL_BATTERY,
    *DEVICE_ARR_TRANS_NORMAL_MAINS
]

DEVICE_ARR_ALL_IGNORE = [
    *DEVICE_ARR_REPEATER
]

# measurable magnitude/quantity:
DEVICE_ARR_ALL_SENSOR_MEAS = [
    *DEVICE_ARR_SENS_TEMP,
    *DEVICE_ARR_SENS_HUMID,
    *DEVICE_ARR_SENS_ENERGY_METER
]

# binary sensors:
DEVICE_ARR_ALL_SENSOR_BINARY = [
    *DEVICE_ARR_SENS_WATER,
    *DEVICE_ARR_SENS_MOTION,
    *DEVICE_ARR_SENS_OPEN_CLOSE,
]

DEVICE_ARR_ALL_SENSOR_MULTI = [
    *DEVICE_ARR_SENS_MULTI,
    *DEVICE_ARR_SENS_WIND,
]

DEVICE_ARR_ALL_SENSOR = [
    *DEVICE_ARR_ALL_SENSOR_MEAS,
    *DEVICE_ARR_ALL_SENSOR_BINARY,
    *DEVICE_ARR_ALL_SENSOR_MULTI,
]

EFC01_EXTA_APP_ID: int = 99

_CMD_RESP_DATA_FIXES_APPEND: str = "append"
_CMD_RESP_DATA_FIXES_RENAME: str = "rename"

_CMD_RESP_DATA_FIXES: dict[ExtaLifeCmd, dict[str, dict[str, str]]] = {
    ExtaLifeCmd.FETCH_RECEIVER_CONFIG_DETAILS: {
        "rename": {
            "available_version": "web_version",
            "new_version": "installed_version",
        }
    },
    ExtaLifeCmd.CHECK_VERSION: {
        "append": {
            "id": EFC01_EXTA_APP_ID,
        }
    },
}

# list of device types mapped into `light` platform in HA
# override device and type rules based on icon; force 'light' device for some icons,
# but only when device was detected preliminary as switch; 28 =LED
DEVICE_ICON_ARR_LIGHT = [
    8,
    9,
    13,
    14,
    15,
    16,
    17
]


class ExtaLifeMessage:
    def __init__(self, command: ExtaLifeCmd = ExtaLifeCmd.NOOP):
        self._command: ExtaLifeCmd = command

    @property
    def command(self) -> ExtaLifeCmd:
        return self._command


class ExtaLifeRequest(ExtaLifeMessage):

    def __init__(self, command: ExtaLifeCmd, data: ExtaLifeData | None = None) -> None:
        super().__init__(command)

        self._data: ExtaLifeData = data if data else {}

    def to_json(self) -> str:
        return json.dumps({"command": self.command, "data": self._data})

    def to_string(self) -> str:
        return str(self.to_json()) if self.command != ExtaLifeCmd.NOOP else " "

    def to_bytes(self) -> bytes:
        return (self.to_string() + chr(3)).encode()


class ExtaLifeResponse(ExtaLifeMessage):

    def __getitem__(self, item: Any) -> ExtaLifeData:
        if isinstance(item, int) and 0 <= item < self.length:
            return self._data[item]
        raise KeyError()

    def __init__(self, response: str | list[ExtaLifeResponseType], request: ExtaLifeRequest | None = None):

        self._request: ExtaLifeRequest | None = request
        self._data: ExtaLifeDataList = []

        if isinstance(response, str):
            # convert to list
            response_data: dict[str, Any] = json.loads(response)
            super().__init__(ExtaLifeCmd(response_data.get("command")))
            self._status: ExtaLifeResponseStatus = ExtaLifeResponseStatus(response_data.get("status"))
            if self.command == ExtaLifeCmd.DOWNLOAD_BACKUP:
                response_data.pop("command")
                response_data.pop("status")
                self._data.append(response_data)
            else:
                data_values: dict[str, Any] | None = response_data.get("data", {})
                if data_values is None:
                    data_values = {"_valid_response": True}
                self._data.append(data_values)
        else:
            super().__init__(response[-1].command)
            self._status: ExtaLifeResponseStatus = response[-1].status
            for x in range(0, len(response)):
                for data_item in response[x]._data:
                    self._data.append(data_item)

    @property
    def request(self) -> ExtaLifeRequest | None:
        return self._request

    @property
    def status(self) -> ExtaLifeResponseStatus:
        return self._status

    @property
    def length(self) -> int:
        return len(self._data)

    @property
    def data(self) -> ExtaLifeDataList:
        return self._data

    @property
    def error_code(self) -> ExtaLifeCmdErrorCode:
        if self.status == ExtaLifeResponseStatus.FAILURE and self.length > 0:
            return ExtaLifeCmdErrorCode(int(self.data[0]["code"]))
        return ExtaLifeCmdErrorCode.SUCCESS

    @property
    def error_message(self) -> str:
        return self.error_code.name


try:
    from .fake_channels import FAKE_RECEIVERS, FAKE_SENSORS, FAKE_TRANSMITTERS  # pylint: disable=unused-import
except ImportError:
    FAKE_RECEIVERS = FAKE_SENSORS = FAKE_TRANSMITTERS = []


class ExtaLifeDeviceFilter(Flag):
    RECEIVERS = auto()
    SENSORS = auto()
    TRANSMITTERS = auto()
    EF_RECEIVER = auto()

    ALL = RECEIVERS | SENSORS | TRANSMITTERS | EF_RECEIVER


class ExtaLifeAPI:
    """ Main API class: wrapper for communication with controller """

    # Actions

    # Channel Types
    CHN_TYP_RECEIVERS = "receivers"
    CHN_TYP_SENSORS = "sensors"
    CHN_TYP_TRANSMITTERS = "transmitters"
    CHN_TYP_EXTA_FREE_RECEIVERS = "exta_free_receivers"

    _debugger: bool | None = None

    @classmethod
    def check_success(cls, response: ExtaLifeResponse, throw_error: bool = True) -> ExtaLifeResponse | None:

        if response.status == ExtaLifeResponseStatus.FAILURE:
            if throw_error:
                _LOGGER.error("ExtaLifeAPI cmd %s FAILURE. Code=%s, %s",
                              response.command.name, response.error_code, response.error_message)
                raise ExtaLifeCmdError(response)

            _LOGGER.warning("ExtaLifeAPI cmd %s FAILURE. Code=%s, %s",
                            response.command.name, response.error_code, response.error_message)
            return None

        fixes = _CMD_RESP_DATA_FIXES.get(response.command)
        if fixes:
            renames = fixes.get(_CMD_RESP_DATA_FIXES_RENAME)
            if renames:
                for response_data in response.data:
                    for fixup_src, fixup_dst in renames.items():
                        value = response_data.get(fixup_src)
                        if value is not None:
                            response_data.pop(fixup_src)
                            response_data.setdefault(fixup_dst, value)

            appends = fixes.get(_CMD_RESP_DATA_FIXES_APPEND)
            if appends:
                for append_key, append_value in appends.items():
                    for response_data in response.data:
                        response_data.update({append_key: append_value})

        return response

    @classmethod
    def discover_controller(cls) -> str:
        """ Returns controller IP address if found, otherwise None"""
        return ExtaLifeConn.discover_controller()

    @classmethod
    def device_make_channel_id(cls, data: dict[str, Any], state: dict[str, Any] | None = None) -> str:
        """create channel_id for specified device. If state is None then 'id' and 'channel' fields are looked up
         in data param, otherwise 'id' is fetched from data and 'channel' from state"""

        if state is None:
            return f"{data.get("id", 81)}-{data.get("channel", "#")}"

        return f"{data.get("id", 81)}-{state.get("channel", "#")}"

    @classmethod
    def device_has_sub_channels(cls, channel_id: str) -> bool:
        """Indicates wherever passed channel_id is sub channel if not contains '#' at last position"""
        return channel_id[-1] != "#"

    @classmethod
    def is_debugger_active(cls) -> bool:
        """Return if the debugger is currently active"""

        if cls._debugger is None:
            cls._debugger = hasattr(sys, "get""trace") and sys.gettrace() is not None
            if not cls._debugger:
                debugger_tool = sys.monitoring.get_tool(sys.monitoring.DEBUGGER_ID)
                cls._debugger = debugger_tool is not None and debugger_tool != ""

        return cls._debugger

    def __init__(self, loop: AbstractEventLoop | None = None,
                 on_connect_callback: Callable[[], Awaitable] | None = None,
                 on_disconnect_callback: Callable[[], Awaitable[int]] | None = None,
                 on_notification_callback: Callable[[ExtaLifeResponse], Awaitable] | None = None):
        """ API Object constructor
        on_connect_callback - optional callback for notifications when API connects to the controller and performs
                              successful login
        on_disconnect_callback - optional callback for notifications when API loses connection to the controller """

        self._mac: str = ""
        self._serial_no: int = 0xFCFFFF
        self._device_type: ExtaLifeDeviceModel = ExtaLifeDeviceModel.EFC01
        self._name: str | None = None

        # set on_connect callback to notify caller
        self._on_connect_callback: Callable[[], Awaitable] | None = on_connect_callback
        self._on_disconnect_callback: Callable[[], Awaitable[int]] | None = on_disconnect_callback
        self._on_notification_callback: Callable[[ExtaLifeResponse], Awaitable] | None = on_notification_callback

        self._loop: AbstractEventLoop = loop if loop is not None else asyncio.get_running_loop()

        self._ver_check_last = 0
        self._ver_check_next = 0
        self._host: str = ""
        self._port: int = 0
        self._recv_timeout: float = 5.0
        self._username: str = ""
        self._password: str = ""
        self._connection: ExtaLifeConn | None = None
        self._network: dict[str, str] = self._create_network_info()
        self._version: dict[str, Any] = self._create_version_info()
        self._reconnect_task: Task | None = None
        # optional observer of all messages exchanged with the controller: callback(direction, message)
        self.traffic_callback: Callable[[str, str], None] | None = None

    def _traffic_dispatch(self, direction: str, message: str) -> None:
        if self.traffic_callback is not None:
            self.traffic_callback(direction, message)

    @staticmethod
    def _config_backup_rotate(backup_path: str, backup_prefix: str, backup_retention: int) -> None:
        # TODO: Missing one-liner
        from pathlib import Path

        if backup_retention <= 0:
            return

        backup_files: dict[str, list[Path]] = {}
        backup_files_size: int = 0
        backup_files_count: int = 0
        path = Path(backup_path)
        for item in path.iterdir():
            if item.is_file() and item.name.startswith(backup_prefix):
                file_base = item.name.rsplit(".", 1)[0]
                backup_files.setdefault(file_base, [])
                backup_files[file_base].append(item)
                backup_files_size += item.stat().st_size
                backup_files_count += 1

        backup_deleted_size: int = 0
        backup_deleted_count: int = 0

        entries = sorted(backup_files.keys())
        entries_len = len(entries)

        if backup_retention and (entries_len - backup_retention > 0):

            _LOGGER.debug("ConfigRotate: Requested rotation to %s entries. Found %s entries. Total %s file(s) of size "
                          "%s byte(s)",
                          backup_retention, entries_len, backup_files_count, backup_files_size)

            for index in range(0, entries_len):
                entry = entries[index]
                for backup_file in backup_files[entry]:
                    if index < entries_len - backup_retention:
                        try:
                            backup_file_size = backup_file.stat().st_size
                            backup_file.unlink(True)
                            backup_deleted_size += backup_file_size
                            backup_deleted_count += 1
                        except OSError as err:
                            _LOGGER.warning("ConfigRotate: Failed to remove '%s', %s", backup_file.name, err)
                            continue

            _LOGGER.debug("ConfigRotate: Removed %s entries. Total %s files of size %s byte(s) has been deleted",
                          entries_len - backup_retention, backup_deleted_count, backup_deleted_size)

        _LOGGER.debug("ConfigRotate: Backup contains %s entries. Total %s file(s) of size %s byte(s)",
                      min(entries_len, backup_retention), backup_files_count - backup_deleted_count,
                      backup_files_size - backup_deleted_size)

    @staticmethod
    def _create_network_info(ip_address: str = "",
                             netmask: str = "",
                             gateway: str = "",
                             dns: str = "") -> dict[str, str]:
        """Build network info dictionary structure"""
        return {
            "ip_address": ip_address,
            "netmask": netmask,
            "gateway": gateway,
            "dns": dns,
        }

    @staticmethod
    def _create_version_info(installed: str = "",
                             web: str = "",
                             update: bool = False,
                             beta: str = "") -> dict[str, Any]:
        """Build version info dictionary structure"""
        return {
            "installed": installed,
            "web": web,
            "update": update,
            "beta": beta,
        }

    @staticmethod
    def _transform_channels(data_list: ExtaLifeDataList) -> list[dict[str, Any]]:
        """
        data_js - list of TCP command data in JSON dict
        dummy_channel - dummy channel number? For Transmitters there is no channel info. Make it # per device

        The method will transform TCP JSON into list of channels.
        Each channel will look like rephrased TCP JSON and will consist of attributes
        of the "state" section (channel) + attributes of the "device" section
        e.g.:

        "devices": [{
           "id": 11,
           "is_powered": false,
           "is_paired": false,
           "set_remove_sensor": false,
           "device": 1,
           "type": 11,
           "serial": 725149,
           "state": {
              "alias": "Room 1-1",
              "channel": 1,
              "icon": 13,
              "is_timeout": false,
              "fav": null,
              "power": 0,
              "last_dir": null,
              "value": null
           }
        }]

        will become:
        [{
           "id": "11-1",
           "data": {
              "alias": "Room 1-1",
              "channel": 1,
              "icon": 13,
              "is_timeout": false,
              "fav": null,
              "power": 0,
              "last_dir": null,
              "value": null,
              "id": 11,
              "is_powered": false,
              "is_paired": false,
              "set_remove_sensor": false,
              "device": 1,
              "type": 11,
              "serial": 725149
           }
        }]
        """

        def channel_get_next() -> int:
            channel_id = 1
            while channel_id in channel_used:
                channel_id += 1

            channel_used.append(channel_id)
            return channel_id

        channels = []  # list of JSON dicts
        for data_item in data_list:
            for device in data_item.get("devices", []):
                dev: dict[str, Any] = device.copy()
                dev.pop("state", None)

                is_exta_free: bool = dev.get("exta_free_device", False) is True
                states: list[dict[str, Any]] = device.get("state", [])
                channel_used = []
                for state in states:

                    if is_exta_free:
                        # do the same as the Exta Life app does - add 300 to move
                        # identifiers to Exta Life "namespace"
                        dev.update({"type": int(state.get("exta_free_type", 0)) + 300})

                    if dev["type"] not in DEVICE_ARR_ALL_TRANSMITTER:
                        if "channel" not in state:
                            state.update({"channel": channel_get_next()})
                        else:
                            channel_used.append(state["channel"])

                    channel = {
                        # API channel, not TCP channel
                        "id": ExtaLifeAPI.device_make_channel_id(device, state),
                        "data": {**state, **dev}
                    }
                    channels.append(channel)
        return channels

    def _config_backup_get_schedule_name(self, ident: str = "", schedule: str = ""):
        # TODO: Missing one-liner
        if not ident:
            ident = self.mac
        if schedule:
            schedule = schedule[0:1].upper() + schedule[1:].lower()
        return f"Backup{schedule}__{ident.replace(".", "_").replace(":", "").upper()}"

    def _config_backup_get_file_base(self, schedule: str = "", ident: str = "") -> str:
        # TODO: Missing one-liner
        return f"{self._config_backup_get_schedule_name(ident, schedule)}__{datetime.now().strftime("%Y%m%d_%H%M%S")}"

    async def _async_reconnect_task(self, reconnect: int) -> None:
        while True:
            await asyncio.sleep(reconnect)
            if self.is_connected:
                _LOGGER.debug("Reconnect skipped, connection is already established")
                break

            try:
                _LOGGER.debug("Reconnect, restoring connection to %s with recv timeout %s seconds...",
                              self.host, self.recv_timeout)
                await self.async_connect(self.username, self.password, self.host, self.port,
                                         recv_timeout=self.recv_timeout, conn_timeout=5.0)
                break

            except ExtaLifeError as err:
                _LOGGER.warning("Reconnect failed will try later, %s", err)

            except Exception as err:  # pylint: disable=broad-except
                # any other error must not stop reconnection attempts
                _LOGGER.warning("Reconnect failed will try later, unexpected error %s", repr(err))

        if self._reconnect_task is asyncio.current_task():
            self._reconnect_task = None

    async def _async_reconnect_task_cancel(self) -> None:
        """Cancel pending reconnect task (unless called from the reconnect task itself)"""

        task = self._reconnect_task
        self._reconnect_task = None
        if task is None or task.done() or task is asyncio.current_task():
            return

        task.cancel()
        with suppress(AsyncCancelledError):
            await task
        _LOGGER.debug("Reconnect task has been finished")

    async def _async_do_conn_connected(self, sender: ExtaLifeConnType) -> None:
        """ Called when connectivity is (re)established and logged on successfully """

        await self._async_reconnect_task_cancel()

        self._connection = sender
        self._host = sender.host
        self._port = sender.port
        self._recv_timeout = sender.recv_timeout
        self._username = sender.username
        self._password = sender.password

        # refresh config details
        config_details: ExtaLifeData | None = await self.async_get_efc_config_details()
        if config_details:
            network = config_details.get("network")
            if network:
                self._name = network.get("name", "")
                mac: str = network.get("mac", "").lower().replace(":", "")
                self._mac = ':'.join(mac[pos:pos + 2] for pos in range(0, len(mac), 2))
                with suppress(ValueError):
                    self._serial_no = int(mac[6:], 16)

            # check if network_actual exists since it is supported from fw ver 1.6.29)
            network_actual = config_details.get("network_actual")
            if network_actual:
                self._network = self._create_network_info(network_actual.get("ip", ""),
                                                          network_actual.get("mask", ""),
                                                          network_actual.get("gate", ""),
                                                          network_actual.get("dns_prime", ""))
            else:
                self._network = self._create_network_info()

        version_info: ExtaLifeData | None = await self.async_check_version(False)
        if version_info:
            self._version = self._create_version_info(version_info.get("installed_version", ""),
                                                      version_info.get("web_version", ""),
                                                      int(version_info.get("update_state", 0)) > 0,
                                                      version_info.get("beta_software", ""))
        else:
            self._version = self._create_version_info()

        if self._on_connect_callback is not None:
            try:
                await self._on_connect_callback()
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Controller EFC-01 %s:%s on connect callback failed", self.host, self.port)

        if self.is_connected:
            _LOGGER.info("Controller EFC-01 %s:%s is now connected", self.host, self.port)
        else:
            _LOGGER.warning("Controller EFC-01 %s:%s is not connected, probably command recv timeout occurred. "
                            "Will try later", self.host, self.port)

    # noinspection PyUnusedLocal
    async def _async_do_conn_disconnected(self, sender: ExtaLifeConnType, should_reconnect: bool) -> None:
        """ Called when connectivity is lost """

        if self.is_connected:
            self._connection = None

            reconnect = 0
            if self._on_disconnect_callback:
                reconnect = await self._on_disconnect_callback()

            if should_reconnect and reconnect > 0:
                _LOGGER.warning("Lost connection to EFC-01 controller, reconnect timer set to %s second(s)", reconnect)
                if self._reconnect_task is None or self._reconnect_task.done():
                    self._reconnect_task = self._loop.create_task(self._async_reconnect_task(reconnect))
            else:
                _LOGGER.info("Connection to EFC-01 controller has been closed")

        self._network = self._create_network_info()
        self._version = self._create_version_info()

    # noinspection PyUnusedLocal
    async def _async_do_conn_notification(self, sender: ExtaLifeConnType, notification: ExtaLifeResponse) -> None:
        """ Called when notification from the controller is received """

        if self._on_notification_callback is not None:
            # forward only device status changes to the listener
            await self._on_notification_callback(notification)

    async def _async_do_conn_event_callback(self, sender: ExtaLifeConnType, event: ExtaLifeEvent, data: Any) -> None:
        if event == ExtaLifeEvent.CONNECTED:
            await self._async_do_conn_connected(sender)
        elif event == ExtaLifeEvent.DISCONNECTED:
            await self._async_do_conn_disconnected(sender, data)
        elif event == ExtaLifeEvent.NOTIFICATION:
            await self._async_do_conn_notification(sender, data)

    async def async_post_command(self, command: ExtaLifeCmd, data: ExtaLifeData | None = None) -> bool:
        """Send command to the controller without waiting for response. Returns True if command was sent"""

        if not self.is_connected:
            _LOGGER.warning("Controller %s is not connected", self.host)
            return False

        try:
            await self._connection.async_post_command(command, data)
        except ExtaLifeError as err:
            _LOGGER.error("Controller %s failed to execute command %s, %s", self.host, command.name, err)
            return False

        return True

    async def async_exec_command(
            self, command: ExtaLifeCmd, data: ExtaLifeData | None = None, resp_timeout: float = -1.0
    ) -> ExtaLifeResponse | None:
        # TODO: Missing one-liner

        if not self.is_connected:
            _LOGGER.warning("Controller %s is not connected", self.host)
            return None

        try:
            return ExtaLifeAPI.check_success(
                await self._connection.async_exec_command(command, data, resp_timeout),
                False
            )
        except ExtaLifeError as err:
            _LOGGER.error("Controller %s failed to execute command %s, %s", self.host, command.name, err)
            return None

    async def async_connect(self, username: str, password: str,
                            host: str | None = None, port: int = 0,
                            conn_timeout: float = 30.0, recv_timeout: float = 5.0, autodiscover: bool = False) -> ExtaLifeData:
        """Connect & authenticate to the controller using user and password parameters"""

        async def _async_connect_tcp(_host: str | None = None, _port: int = 0) -> ExtaLifeConn:

            conn_params: ExtaLifeConnParams = ExtaLifeConnParams(_host, _port, recv_timeout, self._loop)
            conn_params.on_event_callback = self._async_do_conn_event_callback
            conn_params.traffic_callback = self._traffic_dispatch

            tcp_conn = ExtaLifeConn(conn_params)
            try:
                await tcp_conn.async_connect(conn_timeout)

            except Exception as conn_err:
                await tcp_conn.async_disconnect()
                raise conn_err

            return tcp_conn

        # init TCP adapter and try to connect
        try:
            _LOGGER.debug("Connecting to controller using %s",
                          "address " + host if host else "auto discovery procedure")
            connection: ExtaLifeConn = await _async_connect_tcp(host, port)
        except ExtaLifeConnError as err:
            if host and autodiscover:
                _LOGGER.debug(
                    "Connection to %s failed. Probably device has changed its IP address. "
                    "Will try to discover controller new IP address", host)
                connection = await _async_connect_tcp()
            else:
                raise err

        # now try to log in - may raise ExtaLifeConnError
        try:
            response: ExtaLifeResponse = await connection.async_login(username, password)
        except ExtaLifeError as err:
            await connection.async_disconnect()
            raise err

        return response[0]

    async def async_reconnect(self) -> None:
        """ Reconnect with existing connection parameters """

        try:
            await self.async_connect(self.username, self.password, self.host, self.port, recv_timeout=self.recv_timeout, conn_timeout=10.0)
        except ExtaLifeConnError as err:
            _LOGGER.warning("reconnect to EFC-01 at address %s at port %s failed, %s", self.host, self.port, err)

    async def async_disconnect(self, reconnect: bool = False) -> None:
        """ Disconnect from the controller and stop message tasks """
        if not reconnect:
            # stop pending reconnection attempts as well
            await self._async_reconnect_task_cancel()
        if self._connection:
            await self._connection.async_disconnect(reconnect)

    async def async_check_version(self, check_web: bool = False) -> ExtaLifeData | None:
        # TODO: Missing one-liner
        response = await self.async_exec_command(ExtaLifeCmd.CHECK_VERSION, {"check_web_version": check_web},
                                                 self._slow_cmd_timeout if check_web else -1.0)
        if response:
            return response[0]

        return None

    async def async_get_config_backup(self) -> ExtaLifeDataList | None:
        # TODO: Missing one-liner
        response = await self.async_exec_command(ExtaLifeCmd.DOWNLOAD_BACKUP, None, self._slow_cmd_timeout)
        if response:
            result: ExtaLifeDataList = []
            for frame in response.data:
                if frame.get("data_element"):
                    result.append(frame.copy())

            if len(result):
                return result

        return None

    async def async_get_dev_config(self, device_id: int, channel_id: int = 1) -> ExtaLifeData | None:
        # TODO: Missing one-liner
        data: ExtaLifeData = {
            "id": device_id,
            "channel": channel_id,
        }
        response = await self.async_exec_command(ExtaLifeCmd.FETCH_RECEIVER_CONFIG, data)
        if response:
            return response[0]

        return None

    async def async_get_dev_config_details(self, device_id: int, channel_id: int = 1) -> ExtaLifeData | None:
        # TODO: Missing one-liner

        data: ExtaLifeData = {
            "id": device_id,
            "channel": channel_id,
        }
        response = await self.async_exec_command(ExtaLifeCmd.FETCH_RECEIVER_CONFIG_DETAILS, data)
        if response:
            result = response[0]
            result.update(data)

            return result

        return None

    async def async_get_efc_config_details(self) -> ExtaLifeData | None:
        # TODO: Missing one-liner
        response = await self.async_exec_command(ExtaLifeCmd.GET_EFC_CONFIG_DETAILS)
        if response:
            return response[0]

        return None

    async def async_get_network_settings(self) -> ExtaLifeData | None:
        """ Executes command 102 to get network settings and controller name """
        response = await self.async_exec_command(ExtaLifeCmd.FETCH_NETWORK_SETTINGS)
        if response:
            return response[0]

    # async def async_get_channels(self, include=(CHN_TYP_RECEIVERS, CHN_TYP_SENSORS, CHN_TYP_TRANSMITTERS,
    #                                             CHN_TYP_EXTA_FREE_RECEIVERS)) -> ExtaLifeDataList:
    async def async_get_channels(
            self, include: ExtaLifeDeviceFilter = ExtaLifeDeviceFilter.ALL
    ) -> list[dict[str, Any]]:
        """
        Get list of dicts of Exta Life channels consisting of native Exta Life TCP JSON
        data, but with transformed data model. Each channel will have native channel info
        AND device info. 2 channels of the same device will have the same device attributes
        """

        channels: ExtaLifeDataList = []

        async def _async_get_channels(command: ExtaLifeCmd,
                                      more_data: ExtaLifeDataList = None) -> None:

            if self.is_connected:
                response: ExtaLifeResponse = await self.async_exec_command(command)
                if response:
                    if isinstance(more_data, list):
                        response.data.extend(more_data)
                    channels.extend(self._transform_channels(response.data))

        if ExtaLifeDeviceFilter.RECEIVERS in include:
            await _async_get_channels(ExtaLifeCmd.FETCH_RECEIVERS, more_data=FAKE_RECEIVERS)

        if ExtaLifeDeviceFilter.SENSORS in include:
            await _async_get_channels(ExtaLifeCmd.FETCH_SENSORS, more_data=FAKE_SENSORS)

        if ExtaLifeDeviceFilter.TRANSMITTERS in include:
            await _async_get_channels(ExtaLifeCmd.FETCH_TRANSMITTERS, more_data=FAKE_TRANSMITTERS)

        if ExtaLifeDeviceFilter.EF_RECEIVER in include:
            await _async_get_channels(ExtaLifeCmd.FETCH_EXTA_FREE)

        return channels

    async def async_execute_action(self, action, channel_id, **fields) -> ExtaLifeData | None:
        """Execute action/command in controller
        action - action to be performed. See ACTION_* constants
        channel_id - concatenation of device id and channel number e.g. '1-1'
        **fields - fields of the native JSON command e.g. value, mode, mode_val etc

        Returns array of dicts converted from JSON or None if error occurred
        """
        ch_id, channel = channel_id.split("-")
        ch_id = int(ch_id)
        channel = int(channel)

        cmd: ExtaLifeCmd = ExtaLifeCmd.CONTROL_DEVICE
        cmd_data: ExtaLifeData = {
            "id": ch_id,
            "channel": channel,
            "state": ExtaLifeMap.action_to_state(action),
        }
        # this assumes the right fields are passed to the API
        cmd_data.update(**fields)

        response = await self.async_exec_command(cmd, cmd_data)
        if response:
            return response[0]

        return None

    async def async_restart(self) -> bool:
        """ Restart EFC-01 """

        return await self.async_exec_command(ExtaLifeCmd.RESTART, None, self._slow_cmd_timeout) is not None

    async def async_update_controller(self) -> bool:

        response = await self.async_exec_command(ExtaLifeCmd.UPDATE_CONTROLLER, None, self._slow_cmd_timeout)
        return response is not None and response.status == ExtaLifeResponseStatus.SUCCESS

    async def async_update_receiver(self, device_id: int) -> bool:
        cmd: ExtaLifeCmd = ExtaLifeCmd.UPDATE_RECEIVERS
        cmd_data: ExtaLifeData = {"id": device_id}

        return await self.async_post_command(cmd, cmd_data)

    async def async_config_backup(self, path: str, schedule: str = "", retention: int = 0) -> None:
        # TODO: Missing one-liner
        from pathlib import Path

        def write_backup() -> int:
            _file_size: int = 0
            with open(file_name, "w+", encoding="utf-8") as file:
                for backup_item in backup_data:
                    _file_size += file.write(f"{json.dumps(backup_item, separators=(',', ":"))}\n")
            return _file_size

        def write_json() -> int:
            _file_size: int = 0
            with open(file_name, "w+", encoding="utf-8") as file:
                _file_size += file.write(json.dumps(backup_data, indent=2))
            return _file_size

        if not self.is_connected:
            return None

        backup_data = await self.async_get_config_backup()
        if backup_data:
            schedule_name: str = self._config_backup_get_schedule_name(schedule=schedule)
            file_base: str = self._config_backup_get_file_base(schedule=schedule)
            try:
                # file system operations must not block the event loop
                await self._loop.run_in_executor(None, lambda: Path(path).mkdir(parents=True, exist_ok=True))

                file_name: str = os.path.join(path, f"{file_base}.bak")
                size_total: int = 0
                file_size: int = await self._loop.run_in_executor(None, write_backup)
                size_total += file_size
                _LOGGER.debug("ConfigBackup: Wrote %s byte(s) into '%s'", file_size, file_name)

                file_name: str = os.path.join(path, f"{file_base}.json")
                file_size = await self._loop.run_in_executor(None, write_json)
                size_total += file_size
                _LOGGER.debug("ConfigBackup: Wrote %s byte(s) into '%s'", file_size, file_name)

                await self._loop.run_in_executor(
                    None, self._config_backup_rotate, path, schedule_name, retention
                )
                _LOGGER.debug("ConfigBackup: Created successfully, backup contains %s byte(s)", size_total)

            except OSError as err:
                _LOGGER.error("ConfigBackup: config backup for '%s' failed, %s", file_base, err)

        return None

    async def async_config_restore(self, path: str) -> None:
        # TODO: Missing one-liner
        raise NotImplementedError()

    @property
    def _slow_cmd_timeout(self) -> float:
        """Response timeout for commands which take more time on the controller side"""
        return max(self._recv_timeout, 30.0)

    @property
    def is_connected(self) -> bool:
        """ Returns True or False depending of the connection is alive and user is logged on """
        return self._connection is not None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def recv_timeout(self) -> float:
        return self._recv_timeout

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str:
        return self._password

    @property
    def serial_no(self) -> int:
        return self._serial_no

    @property
    def mac(self) -> str:
        return self._mac

    @property
    def name(self) -> str:
        """ Get controller name from buffer """
        return self._name

    @property
    def version_installed(self) -> str:
        return self._version["installed"]

    @property
    def version_web(self) -> str:
        return self._version["web"]

    @property
    def version_update(self) -> bool:
        return self._version["update"]

    @property
    def version_beta(self) -> str:
        return self._version["beta"]

    @property
    def ver_check_last(self) -> str | None:
        if self._ver_check_last:
            return datetime.fromtimestamp(self._ver_check_last).strftime('%Y.%m.%d, %H:%M:%S')
        return None

    @property
    def ver_check_next(self) -> str | None:
        if self._ver_check_next:
            return datetime.fromtimestamp(self._ver_check_next).strftime('%Y.%m.%d, %H:%M:%S')
        return None

    @property
    def network(self) -> dict[str, str]:
        return self._network

    def ver_check_required(self) -> bool:
        return self._ver_check_next != 0 and datetime.now().timestamp() > self._ver_check_next

    def ver_check_set(self, next_update: int, last_update: bool = False) -> bool:

        changed: bool = False

        if last_update:
            self._ver_check_last = datetime.now().timestamp()
            changed = True

        if next_update < 0:
            self._ver_check_next = 0
            changed = True

        elif next_update > 0:
            last: float = self._ver_check_last if self._ver_check_last else datetime.now().timestamp()
            self._ver_check_next = int(last + next_update)
            changed = True

        return changed


class ExtaLifeError(Exception):

    def __init__(self) -> None:
        super().__init__()

    def __str__(self) -> str:
        return self.message

    @property
    def code(self) -> int:
        raise NotImplementedError()

    @property
    def message(self) -> str:
        raise NotImplementedError()


class ExtaLifeConnError(ExtaLifeError):

    def __init__(self, message: str, code: int = 0) -> None:
        """Empty constructor"""
        super().__init__()
        self._message = message
        self._code = code

    @property
    def code(self) -> int:
        return self._code

    @property
    def message(self) -> str:
        return f"{self._message if self._message else ""}"


class ExtaLifeDataError(ExtaLifeError):

    def __init__(self, message: str, code: int = 0) -> None:
        """Empty constructor"""
        super().__init__()
        self._message = message
        self._code = code

    @property
    def code(self) -> int:
        return self._code

    @property
    def message(self) -> str:
        return f"{self._message if self._message else ""}"


class ExtaLifeCmdError(ExtaLifeError):

    def __init__(self, response: ExtaLifeResponse) -> None:
        super().__init__()
        self._response = response

    @property
    def command(self) -> ExtaLifeCmd:
        return self._response.command

    @property
    def code(self) -> ExtaLifeCmdErrorCode:
        return self._response.error_code

    @property
    def message(self) -> str:
        return (f"Command '{self.command.name}' failed. "
                f"Error code {self.code}, {self._response.error_message}")


class ExtaLifeConnParams:
    EFC01_DEFAULT_PORT = 20400

    @classmethod
    def get_addr(cls, host: str, port: int) -> str:
        result = host
        if port != 0 and port != cls.EFC01_DEFAULT_PORT:
            result += ":" + str(port)
        return result

    @classmethod
    def get_host_and_port(cls, addr: str) -> tuple[str, int]:
        """split provided addr as host and port"""
        host: str = (addr or "").strip()
        port: int = cls.EFC01_DEFAULT_PORT
        if host.count(":") == 1:
            host, port_str = host.split(":")
            try:
                port = int(port_str) if port_str else cls.EFC01_DEFAULT_PORT
            except ValueError:
                port = cls.EFC01_DEFAULT_PORT

        if not 0 < port <= 65535:
            port = cls.EFC01_DEFAULT_PORT

        return host, port

    def __init__(self, host: str, port: int, recv_timeout: float, eventloop: AbstractEventLoop, keepalive: float = 8):

        self._eventloop: AbstractEventLoop = eventloop
        self._host: str = host
        self._port: int = port if (port > 0) and (port <= 65535) else self.EFC01_DEFAULT_PORT
        self._recv_timeout: float = recv_timeout
        self._keepalive: float = keepalive

        self.on_event_callback: Callable[[ExtaLifeConnType, ExtaLifeEvent, Any], Awaitable] | None = None
        # called with direction ("in" / "out") and raw message for every message exchanged with controller
        self.traffic_callback: Callable[[str, str], None] | None = None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def recv_timeout(self) -> float:
        return self._recv_timeout

    @property
    def keepalive(self) -> float:
        return self._keepalive

    @property
    def eventloop(self) -> AbstractEventLoop:
        return self._eventloop


class ExtaLifeConn:
    class CloseSource(StrEnum):
        CONNECT = "connect"
        CONN_TASK = "conn_task"
        DISCONNECT = "disconnect"
        PING_TASK = "ping_task"
        READ_TASK = "read_task"
        REQUEST = "request"

    TCP_BUFF_SIZE = 8192
    # maximum size of a single message from controller (StreamReader default is 64 KiB)
    TCP_READ_LIMIT = 4 * 1024 * 1024

    def __init__(self, params: ExtaLifeConnParams) -> None:

        self._eventloop: AbstractEventLoop = params.eventloop
        self._host: str = params.host
        self._port: int = params.port
        self._recv_timeout: float = params.recv_timeout

        self._local_addr: str = ""
        self._local_port: int = -1
        self._remote_addr: str = ""
        self._remote_port: int = -1
        self._keepalive: float = params.keepalive

        self._on_event_callback: Callable[
                                     [ExtaLifeConnType, ExtaLifeEvent, Any], Awaitable
                                 ] | None = params.on_event_callback
        self._traffic_callback: Callable[[str, str], None] | None = params.traffic_callback

        self._username: str = ""
        self._password: str = ""
        self._tcp_reader: StreamReader | None = None
        self._tcp_writer: StreamWriter | None = None
        self._write_lock: Lock = Lock()
        self._cmd_exec_lock: Lock = Lock()
        self._socket = None
        self._ping_task: Task | None = None
        self._read_task: Task | None = None

        self._tcp_last_write: float = time.monotonic()

        self._response_handlers: list[Callable[[ExtaLifeResponse], None]] = []
        self._pending_requests: set[asyncio.Future] = set()

    async def _task_shutdown(
            self, task_name: CloseSource, task: Task, close_source: CloseSource
    ) -> None:

        if task and task is not asyncio.current_task():
            if task_name != close_source:
                _LOGGER.debug("_task_shutdown[%s:%s] task '%s' requesting cancellation",
                              self.host, close_source.name, task_name.name)
                task.cancel()

            try:
                await task
            except AsyncCancelledError:
                _LOGGER.debug("_task_shutdown[%s:%s] task '%s' canceled", self.host, close_source.name, task_name.name)
                pass

        return None

    async def _async_do_event(self, event: ExtaLifeEvent, data: Any = None) -> None:
        """Notify of event by calling provided callback"""

        if self._on_event_callback is not None:
            await self._on_event_callback(self, event, data)

    async def _async_close(self, close_source: CloseSource) -> None:

        if self._socket is None:
            return

        _LOGGER.debug("_async_close[%s:%s]: closing connection", self.host, close_source.name)

        self._ping_task = await self._task_shutdown(ExtaLifeConn.CloseSource.PING_TASK, self._ping_task, close_source)
        self._read_task = await self._task_shutdown(ExtaLifeConn.CloseSource.READ_TASK, self._read_task, close_source)

        async with self._write_lock:
            if not self._socket:
                _LOGGER.debug("_async_close[%s:%s]: connection already closed", self.host, close_source.name)
                # socket could be released during awaiting on lock. if so just return
                return

            self._local_addr = ""
            self._local_port = -1
            self._remote_addr = ""
            self._remote_port = -1

            if self._tcp_writer:
                self._tcp_writer.close()
                self._tcp_writer = None

            self._tcp_reader = None

            self._socket.close()
            self._socket = None

        # fail all requests awaiting response - they will never get one
        for pending in list(self._pending_requests):
            if not pending.done():
                pending.set_exception(ExtaLifeConnError("connection to controller has been closed"))
        self._pending_requests.clear()

        _LOGGER.debug("_async_close[%s:%s]: connection closed", self.host, close_source.name)

        should_reconnect = False if close_source == ExtaLifeConn.CloseSource.DISCONNECT else True
        await self._async_do_event(ExtaLifeEvent.DISCONNECTED, should_reconnect)

    async def _async_read_task(self) -> None:

        _LOGGER.debug("_async_read_task[%s]: STARTED", self.host)
        try:
            while True:
                response_raw: bytes = (await self._tcp_reader.readuntil(chr(3).encode()))[:-1]
                self._traffic("in", response_raw.decode(errors="replace"))

                try:
                    response_str: str = response_raw.decode()
                    response: ExtaLifeResponse = ExtaLifeResponse(response_str)
                except (ValueError, KeyError, TypeError, AttributeError) as err:
                    # unknown command / status (e.g. after controller firmware update) or malformed message
                    # must not break the whole connection - just skip this message
                    _LOGGER.warning("_async_read_task[%s]: ignoring unsupported message %s, %s",
                                    self.host, response_raw[:512], repr(err))
                    continue

                _LOGGER.debug("<<< [Cmd=%s] %s", response.command.name, response_str)

                # pass only status change notifications to registered listeners
                if response.status == ExtaLifeResponseStatus.NOTIFICATION:
                    try:
                        await self._async_do_event(ExtaLifeEvent.NOTIFICATION, response)
                    except Exception:  # pylint: disable=broad-except
                        _LOGGER.exception("_async_read_task[%s]: notification processing failed", self.host)

                for response_handler in self._response_handlers[:]:
                    try:
                        response_handler(response)
                    except Exception:  # pylint: disable=broad-except
                        _LOGGER.exception("_async_read_task[%s]: response handler failed", self.host)

        except AsyncCancelledError:
            _LOGGER.debug("_async_read_task[%s]: CANCELLED", self.host)
            pass

        except Exception as err:
            self._read_task = None
            _LOGGER.error("_async_read_task[%s]: FAILURE - error while reading incoming messages, %s",
                          self.host, str(err))
            await self._async_close(ExtaLifeConn.CloseSource.READ_TASK)

        finally:
            _LOGGER.debug("_async_read_task[%s]: FINISHED", self.host)

    async def _async_ping_task(self) -> None:
        """Perform dummy data posting to connected controller"""

        _LOGGER.debug("_async_ping_task[%s]: STARTED", self.host)
        try:
            while True:
                last_write = time.monotonic() - self._tcp_last_write
                if last_write < self._keepalive:
                    period = self._keepalive - last_write
                    await asyncio.sleep(period)
                else:
                    await self.async_post_command(ExtaLifeCmd.NOOP)

        except AsyncCancelledError:
            _LOGGER.debug("_async_ping_task[%s]: CANCELLED", self.host)

        except Exception as err:
            _LOGGER.error("_async_ping_task[%s]: FAILURE - error while pinging controller, %s", self.host, str(err))
            await self._async_close(ExtaLifeConn.CloseSource.PING_TASK)

        finally:
            _LOGGER.debug("_async_ping_task[%s]: FINISHED", self.host)

    async def _async_post_data(self, data: bytes) -> None:

        if self._socket is None or self._tcp_writer is None:
            raise ExtaLifeConnError(f"_async_post_data[{self.host}]: host is not connected")

        try:
            async with self._write_lock:
                self._tcp_writer.write(data)
                self._tcp_last_write = time.monotonic()
                await self._tcp_writer.drain()
        except OSError as err:
            await self._async_close(ExtaLifeConn.CloseSource.REQUEST)
            raise ExtaLifeConnError(f"post_data failed, {err}", err.errno) from None

    async def _async_post_request(self, request: ExtaLifeRequest) -> None:

        request_data = request.to_bytes()
        request_str = str(request_data)
        if request.command == ExtaLifeCmd.LOGIN and not ExtaLifeAPI.is_debugger_active():
            request_str = re.sub(r'"password":\s*"[^"]*"', '"password": "********"', request_str)
        _LOGGER.debug(">>> [Cmd=%s] %s", request.command.name, request_str)
        if request.command != ExtaLifeCmd.NOOP:
            self._traffic("out", request.to_json())

        await self._async_post_data(request_data)

    def _traffic(self, direction: str, message: str) -> None:
        """Pass exchanged message to traffic callback (e.g. traffic recorder)"""
        if self._traffic_callback is None:
            return
        try:
            self._traffic_callback(direction, message)
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Traffic callback failed")

    async def _async_send_request(
            self, request: ExtaLifeRequest, resp_timeout: float
    ) -> list[ExtaLifeResponse]:
        """ Send message to controller and await response """

        if resp_timeout < 0:
            resp_timeout = self.recv_timeout

        # prevent controller overloading and command loss - wait until finished (lock released)
        async with self._cmd_exec_lock:

            if self._socket is None:
                raise ExtaLifeConnError(f"send_request[{self.host}]: host is not connected")

            responses: list[ExtaLifeResponse] = []
            response_reader: asyncio.Future = self._eventloop.create_future()
            last_response: float = time.monotonic()

            def on_response(response: ExtaLifeResponse) -> None:

                nonlocal last_response

                if response_reader.done() or response.command != request.command:
                    return

                if response.status == ExtaLifeResponseStatus.NOTIFICATION:
                    last_response = time.monotonic()

                elif response.status in (ExtaLifeResponseStatus.SEARCHING,
                                         ExtaLifeResponseStatus.PARTIAL,
                                         ExtaLifeResponseStatus.PROGRESS):
                    last_response = time.monotonic()
                    responses.append(response)

                elif response.status in (ExtaLifeResponseStatus.SUCCESS, ExtaLifeResponseStatus.FAILURE):
                    responses.append(response)
                    response_reader.set_result(responses)

            self._response_handlers.append(on_response)
            self._pending_requests.add(response_reader)
            try:
                await self._async_post_request(request)

                # wait until final response arrives; every partial response restarts the timeout
                while not response_reader.done():
                    remaining = resp_timeout - (time.monotonic() - last_response)
                    if remaining <= 0:
                        self._pending_requests.discard(response_reader)
                        response_reader.cancel()
                        await self._async_close(ExtaLifeConn.CloseSource.REQUEST)
                        raise ExtaLifeConnError("send_request failed, timeout while waiting for API response")

                    with suppress(AsyncTimeoutError):
                        await asyncio.wait_for(asyncio.shield(response_reader), remaining)

                return response_reader.result()

            finally:
                self._pending_requests.discard(response_reader)
                if response_reader.done() and not response_reader.cancelled():
                    # mark exception (if any) as retrieved
                    response_reader.exception()
                with suppress(ValueError):
                    self._response_handlers.remove(on_response)

    async def async_post_command(self, command: ExtaLifeCmd, data: ExtaLifeData | None = None) -> None:
        await self._async_post_request(ExtaLifeRequest(command, data))

    async def async_exec_command(
            self, command: ExtaLifeCmd, data: ExtaLifeData | None = None, resp_timeout: float = -1.0
    ) -> ExtaLifeResponse:

        request = ExtaLifeRequest(command, data)
        responses = await self._async_send_request(request, resp_timeout)
        if len(responses) == 0:
            raise ExtaLifeConnError("exec_command failed, no response received from Controller")

        return ExtaLifeResponse(responses, request)

    async def async_connect(self, timeout: float = 30.0) -> None:
        """Connect to EFC-01 via TCP socket"""
        if self.connected:
            raise ExtaLifeConnError("ExtaLifeConn async_connect failed, already connected")

        if not self._host:
            # if host is empty we should activate discovery action
            self._host = await self._eventloop.run_in_executor(None, ExtaLifeConn.discover_controller)
            if not self._host:
                raise ExtaLifeConnError("Failed to discover controller on local network")
            # if host was found we change connection port to default EFC-01 port (20400)
            self._port = ExtaLifeConnParams.EFC01_DEFAULT_PORT

        try:
            addr_info = await self._eventloop.getaddrinfo(self.host, self.port, family=socket.AF_INET,
                                                          type=socket.SOCK_STREAM)
        except OSError as err:
            raise ExtaLifeConnError(f"Unable to resolve {self.host}, {err}") from err

        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.setblocking(False)
        self._socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        _LOGGER.debug("Trying to connect to %s at port %s", self.host, self.port)
        try:
            coro = self._eventloop.sock_connect(self._socket, addr_info[0][4])
            await asyncio.wait_for(coro, timeout)

        except TimeoutError as err:
            await self._async_close(ExtaLifeConn.CloseSource.CONNECT)
            raise ExtaLifeConnError(f"Unable to connect {self.host}, connection timed out") from err

        except OSError as err:
            await self._async_close(ExtaLifeConn.CloseSource.CONNECT)
            raise ExtaLifeConnError(f"Unable to connect {self.host}, connection refused") from err

        self._local_addr, self._local_port = self._socket.getsockname()
        self._remote_addr, self._remote_port = self._socket.getpeername()

        self._tcp_reader, self._tcp_writer = await asyncio.open_connection(sock=self._socket,
                                                                            limit=self.TCP_READ_LIMIT)

        self._read_task = self._eventloop.create_task(self._async_read_task())
        self._ping_task = self._eventloop.create_task(self._async_ping_task())

        _LOGGER.debug("async_connect[%s] successfully connected (%s:%s <==> %s:%s)",
                      self.host, self._local_addr, self._local_port, self._remote_addr, self._remote_port)

    async def async_login(self, username: str, password: str) -> ExtaLifeResponse | None:
        """
        Try to log on via command: 1
        return json dictionary with result or exception in case of connection or logon
        problem
        """
        if not self.connected:
            raise ExtaLifeConnError("async_login, not connected")
        if self.authenticated:
            raise ExtaLifeConnError("async_login, user already logged in")

        pwd = password if ExtaLifeAPI.is_debugger_active() else "*" * len(password)
        _LOGGER.debug("logging in... [user: '%s', password: '%s']", username, pwd)

        cmd_data = {"password": password, "login": username}

        response = ExtaLifeAPI.check_success(await self.async_exec_command(ExtaLifeCmd.LOGIN, cmd_data))

        _LOGGER.debug("user '%s' authenticated", username)
        self._username = username
        self._password = password

        await self._async_do_event(ExtaLifeEvent.CONNECTED, self)

        return response

    async def async_disconnect(self, reconnect: bool = False) -> None:
        await self._async_close(ExtaLifeConn.CloseSource.REQUEST if reconnect else ExtaLifeConn.CloseSource.DISCONNECT)

    @property
    def authenticated(self) -> bool:
        return self._username != ""

    @property
    def connected(self) -> bool:
        return self._socket is not None

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def recv_timeout(self) -> float:
        return self._recv_timeout

    @property
    def username(self) -> str:
        return self._username

    @property
    def password(self) -> str:
        return self._password

    @property
    def local_addr(self) -> str:
        return self._local_addr

    @property
    def local_port(self) -> int:
        return self._local_port

    @property
    def remote_addr(self) -> str:
        return self._remote_addr

    @property
    def remote_port(self) -> int:
        return self._remote_port

    @staticmethod
    def discover_controller() -> str:
        """
        Perform controller autodiscovery using UDP query
        return IP as string or false if not found
        """
        multicast_group: str = "225.0.0.1"
        multicast_port: int = 20401
        import struct

        # sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server_address = ("", multicast_port)

        # Create the socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        try:
            # Bind to the server address
            try:
                sock.bind(server_address)
            except OSError:
                _LOGGER.error("Could not connect to receive UDP multicast from EFC-01 on port %s", multicast_port)
                return ""

            # Tell the operating system to add the socket to the multicast group
            # on all interfaces (join multicast group)
            group = socket.inet_aton(multicast_group)
            multicast_req = struct.pack("4sL", group, socket.INADDR_ANY)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, multicast_req)

            sock.settimeout(3)
            try:
                (data, address) = sock.recvfrom(1024)
            except OSError:
                return ""
        finally:
            sock.close()

        _LOGGER.debug("Got multicast response from EFC-01: %s", data)

        try:
            response = ExtaLifeResponse(data.decode().rstrip(chr(3)))
        except (ValueError, KeyError, TypeError, UnicodeDecodeError) as err:
            _LOGGER.debug("Unsupported multicast message, %s", err)
            return ""

        if response.status == ExtaLifeResponseStatus.BROADCAST and response.command == ExtaLifeCmd.NOOP:
            return address[0]  # return IP - array[0]; array[1] is sender's port
        return ""
