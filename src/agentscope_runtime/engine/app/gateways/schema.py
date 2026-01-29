# -*- coding: utf-8 -*-

from typing import Literal
from pydantic import BaseModel

ChannelType = Literal["imessage", "discord"]


class Incoming(BaseModel):
    channel: ChannelType
    sender: str
    text: str
    meta: dict = {}
