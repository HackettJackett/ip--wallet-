#!/usr/bin/env python
#
# Electrum - lightweight Bitcoin client
# Copyright (C) 2019 The Electrum Developers
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
import os
import ast
import json
import copy
import threading
import binascii

from . import util
from .logging import Logger

JsonDBJsonEncoder = util.MyEncoder


def modifier(func):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            self._modified = True
            return func(self, *args, **kwargs)
    return wrapper

def locked(func):
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return func(self, *args, **kwargs)
    return wrapper


def key_path(path, key):
    def to_str(x):
        if isinstance(x, int):
            return str(int(x))
        else:
            assert isinstance(x, str)
            return x
    return '/' + '/'.join([to_str(x) for x in path + [to_str(key)]])

registered_names = {}
registered_dicts = {}
registered_dict_keys = {}
registered_parent_keys = {}


def stored_as(name, _type=dict):
    def decorator(func):
        registered_names[name] = func, _type
        return func
    return decorator

def stored_in(name, _type=dict):
    def decorator(func):
        registered_dicts[name] = func, _type
        return func
    return decorator



class StoredObject:

    db = None
    path = None

    def __setattr__(self, key, value):
        if self.db and key not in ['path', 'db'] and not key.startswith('_'):
            self.db.add_patch({'op': 'replace', 'path': key_path(self.path, key), 'value': value})
        object.__setattr__(self, key, value)

    def set_db(self, db, path):
        self.db = db
        self.path = path

    def to_json(self):
        d = dict(vars(self))
        d.pop('db', None)
        d.pop('path', None)
        # don't expose/store private stuff
        d = {k: v for k, v in d.items()
             if not k.startswith('_')}
        return d


_RaiseKeyError = object() # singleton for no-default behavior

class StoredDict(dict):

    def __init__(self, data, db, path):
        self.db = db
        self.lock = self.db.lock if self.db else threading.RLock()
        self.path = path
        # recursively convert dicts to StoredDict
        for k, v in list(data.items()):
            self.__setitem__(k, v, patch=False)

    @locked
    def __setitem__(self, key, v, patch=True):
        is_new = key not in self
        # early return to prevent unnecessary disk writes
        if not is_new and self[key] == v and patch is True:
            return
        # recursively set db and path
        if isinstance(v, StoredDict):
            assert v.db is None
            v.db = self.db
            v.path = self.path + [key]
            for k, vv in v.items():
                v.__setitem__(k, vv, patch=False)
        # recursively convert dict to StoredDict.
        # _convert_dict is called breadth-first
        elif isinstance(v, dict):
            if self.db:
                v = self.db._convert_dict(self.path, key, v)
            if not self.db or self.db._should_convert_to_stored_dict(key):
                v = StoredDict(v, self.db, self.path + [key])
        # convert_value is called depth-first
        if isinstance(v, dict) or isinstance(v, str):
            if self.db:
                v = self.db._convert_value(self.path, key, v)
        # set parent of StoredObject
        if isinstance(v, StoredObject):
            v.set_db(self.db, self.path + [key])
        # set item
        dict.__setitem__(self, key, v)
        if self.db and patch:
            op = 'add' if is_new else 'replace'
            self.db.add_patch({'op': op, 'path': key_path(self.path, key), 'value': v})

    @locked
    def __delitem__(self, key):
        dict.__delitem__(self, key)
        if self.db:
            self.db.add_patch({'op': 'remove', 'path': key_path(self.path, key)})

    @locked
    def pop(self, key, v=_RaiseKeyError):
        if key not in self:
            if v is _RaiseKeyError:
                raise KeyError(key)
            else:
                return v
        r = dict.pop(self, key)
        if self.db:
            self.db.add_patch({'op': 'remove', 'path': key_path(self.path, key)})
        return r


class StorageList:

    def __init__(self, data, db, path):
        self.l = [data[str(i)] for i in range(len(data))]
        self.db = db
        self.path = path
        self.lock = self.db.lock if self.db else threading.RLock()

    def locked(func):
        def wrapper(self, *args, **kwargs):
            with self.lock:
                r = func(self, *args, **kwargs)
                return r
        return wrapper

    @locked
    def to_json(self):
        return dict(enumerate(self.l))

    @locked
    def __getitem__(self, key):
        return self.l.__getitem__(key)

    @locked
    def __contains__(self, v):
        return self.l.__contains__(v)

    @locked
    def __len__(self):
        return self.l.__len__()

    @locked
    def count(self, v):
        return self.l.count(v)

    @locked
    def append(self, x):
        self.l.append(x)
        if self.db:
            self.db.set_modified(True)

    @locked
    def remove(self, x):
        self.l.remove(x)
        if self.db:
            self.db.set_modified(True)

    @locked
    def clear(self):
        self.l.clear()
        if self.db:
            self.db.set_modified(True)

    @locked
    def reverse(self):
        self.l.reverse()




class JsonDB(Logger):

    def __init__(self, data):
        Logger.__init__(self)
        self.lock = threading.RLock()
        self.data = data
        self.pending_changes = []
        self._modified = False

    def set_modified(self, b):
        with self.lock:
            self._modified = b

    def modified(self):
        return self._modified

    def add_patch(self, patch):
        self.pending_changes.append(json.dumps(patch, cls=JsonDBJsonEncoder))

    @locked
    def get(self, key, default=None):
        v = self.data.get(key)
        if v is None:
            v = default
        return v

    @modifier
    def put(self, key, value):
        try:
            json.dumps(key, cls=JsonDBJsonEncoder)
            json.dumps(value, cls=JsonDBJsonEncoder)
        except:
            self.logger.info(f"json error: cannot save {repr(key)} ({repr(value)})")
            return False
        if value is not None:
            if self.data.get(key) != value:
                self.data[key] = copy.deepcopy(value)
                return True
        elif key in self.data:
            self.data.pop(key)
            return True
        return False

    @locked
    def dump(self, *, human_readable: bool = True) -> str:
        """Serializes the DB as a string.
        'human_readable': makes the json indented and sorted, but this is ~2x slower
        """
        return json.dumps(
            self.data,
            indent=4 if human_readable else None,
            sort_keys=bool(human_readable),
            cls=JsonDBJsonEncoder,
        )

    def _should_convert_to_stored_dict(self, key) -> bool:
        return True

    def register_dict(self, name, method, _type):
        registered_dicts[name] = method, _type

    def register_name(self, name, method, _type):
        registered_names[name] = method, _type

    def register_dict_key(self, name, method):
        registered_dict_keys[name] = method

    def register_parent_key(self, name, method):
        registered_parent_keys[name] = method

    def _convert_dict(self, path, key, v):

        if key in registered_dicts:
            constructor, _type = registered_dicts[key]
            if _type == dict:
                v = dict((k, constructor(**x)) for k, x in v.items())
            elif _type == tuple:
                v = dict((k, constructor(*x)) for k, x in v.items())
            else:
                v = dict((k, constructor(x)) for k, x in v.items())

        if key in registered_dict_keys:
            convert_key = registered_dict_keys[key]
        elif path and path[-1] in registered_parent_keys:
            convert_key = registered_parent_keys.get(path[-1])
        else:
            convert_key = None
        if convert_key:
            v = dict((convert_key(k), x) for k, x in v.items())

        return v

    def _convert_value(self, path, key, v):
        if key in registered_names:
            constructor, _type = registered_names[key]
            if _type == dict:
                v = constructor(**v)
            else:
                v = constructor(v, path, key)
        return v
