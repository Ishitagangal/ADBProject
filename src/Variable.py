import os
import sys
import time


class Variable():
    def __init__(self, name, index, value):
        self.name = name
        self.value = value
        self.index = index
        self.lock_type = None
        self.locked = False
        self.latestUpdate = 0 # timestamp

    def get_list_of_sites(self, id):
        return

    def get_value(self):
        return self.value

    def __set__(self, value):
        self.value = value

    def is_locked(self):
        return self.lock_type

    def set_lock_type(self, lock_type ):
        self.lock_type = lock_type


