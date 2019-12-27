#!/usr/bin/env python3
"""
Defines the default object transformers
"""

from typing import List, Optional
import functools

from .core import read, read_string, to_bytes, log_error, log_debug
from .deserialize import constants
from .deserialize.beans import BlockData, JavaClassDesc, JavaInstance
from .deserialize.core import JavaStreamParser
from .deserialize.stream import DataStreamReader


class JavaList(list, JavaInstance):
    """
    Python-Java list bridge type
    """

    HANDLED_CLASSES = ("java.util.ArrayList", "java.util.LinkedList")

    def __init__(self):
        list.__init__(self)
        JavaInstance.__init__(self)

    def load_from_instance(self, instance, indent=0):
        # type: (JavaInstance, int) -> bool
        """
        Load content from a parsed instance object
        """
        # Lists have their content in there annotations
        for cd, annotations in instance.annotations.items():
            if cd.name in self.HANDLED_CLASSES:
                self.extend(ann for ann in annotations[1:])
                return True

        return False

@functools.total_ordering
class JavaPrimitiveClass(JavaInstance):
    """
    Parent of Java classes matching a primitive (Bool, Integer, Long, ...)
    """

    def __init__(self):
        JavaInstance.__init__(self)
        self.value = None

    def __str__(self):
        return str(self.value)

    def __repr__(self):
        return repr(self.value)

    def __hash__(self):
        return hash(self.value)

    def __eq__(self, other):
        return self.value == other

    def __lt__(self, other):
        return self.value < other

    def load_from_instance(self, instance, indent=0):
        # type: (JavaInstance, int) -> bool
        """
        Load content from a parsed instance object
        """
        for field, value in instance.field_data.values():
            if field.name == "value":
                self.value = value
                return True

        return False


class JavaBool(JavaPrimitiveClass):
    HANDLED_CLASSES = "java.lang.Boolean"

    def __bool__(self):
        return self.value


class JavaInt(JavaPrimitiveClass):

    HANDLED_CLASSES = ("java.util.Integer", "java.util.Long")

    def __int__(self):
        return self.value


class JavaMap(dict, JavaInstance):
    """
    Python-Java dictionary/map bridge type
    """

    HANDLED_CLASSES = ("java.util.HashMap", "java.util.TreeMap")

    def __init__(self):
        dict.__init__(self)
        JavaInstance.__init__(self)

    def load_from_instance(self, instance, indent=0):
        # type: (JavaInstance, int) -> bool
        """
        Load content from a parsed instance object
        """
        # Lists have their content in there annotations
        for cd, annotations in instance.annotations.items():
            if cd.name in JavaMap.HANDLED_CLASSES:
                # Group annotation elements 2 by 2
                args = [iter(annotations[1:])] * 2
                for key, value in zip(*args):
                    self[key] = value

                return True

        return False


class JavaLinkedHashMap(JavaMap):
    """
    Linked has map are handled with a specific block data
    """

    HANDLED_CLASSES = "java.util.LinkedHashMap"

    def load_from_blockdata(self, parser, reader, indent=0):
        # type: (JavaStreamParser, DataStreamReader, int) -> bool
        """
        Loads the content of the map, written with a custom implementation
        """
        # Read HashMap fields
        self.buckets = reader.read_int()
        self.size = reader.read_int()

        # Read entries
        for _ in range(self.size):
            key_code = reader.read_byte()
            key = parser._read_content(key_code, True)

            value_code = reader.read_byte()
            value = parser._read_content(value_code, True)
            self[key] = value

        # Ignore the end of the blockdata
        type_code = reader.read_byte()
        if type_code != constants.TC_ENDBLOCKDATA:
            raise ValueError("Didn't find the end of block data")

        # Ignore the trailing 0
        final_byte = reader.read_byte()
        if final_byte != 0:
            raise ValueError("Should find 0x0, got {0:x}".format(final_byte))

        return True


class JavaSet(set, JavaInstance):
    """
    Python-Java set bridge type
    """

    HANDLED_CLASSES = ("java.util.HashSet", "java.util.LinkedHashSet")

    def __init__(self):
        set.__init__(self)
        JavaInstance.__init__(self)

    def load_from_instance(self, instance, indent=0):
        # type: (JavaInstance, int) -> bool
        """
        Load content from a parsed instance object
        """
        # Lists have their content in there annotations
        for cd, annotations in instance.annotations.items():
            if cd.name in self.HANDLED_CLASSES:
                self.update(x for x in annotations[1:])
                return True

        return False


class JavaTreeSet(JavaSet):
    """
    Tree sets are handled a bit differently
    """

    HANDLED_CLASSES = "java.util.TreeSet"

    def load_from_instance(self, instance, indent=0):
        # type: (JavaInstance, int) -> bool
        """
        Load content from a parsed instance object
        """
        # Lists have their content in there annotations
        for cd, annotations in instance.annotations.items():
            if cd.name == self.HANDLED_CLASSES:
                # Annotation[1] == size of the set
                self.update(x for x in annotations[2:])
                return True

        return False


class JavaTime(JavaInstance):
    """
    Represents the classes found in the java.time package

    The semantic of the fields depends on the type of time that has been
    parsed
    """

    HANDLED_CLASSES = "java.time.Ser"

    DURATION_TYPE = 1
    INSTANT_TYPE = 2
    LOCAL_DATE_TYPE = 3
    LOCAL_TIME_TYPE = 4
    LOCAL_DATE_TIME_TYPE = 5
    ZONE_DATE_TIME_TYPE = 6
    ZONE_REGION_TYPE = 7
    ZONE_OFFSET_TYPE = 8
    OFFSET_TIME_TYPE = 9
    OFFSET_DATE_TIME_TYPE = 10
    YEAR_TYPE = 11
    YEAR_MONTH_TYPE = 12
    MONTH_DAY_TYPE = 13
    PERIOD_TYPE = 14

    def __init__(self):
        JavaInstance.__init__(self)
        self.type = -1
        self.year = None
        self.month = None
        self.day = None
        self.hour = None
        self.minute = None
        self.second = None
        self.nano = None
        self.offset = None
        self.zone = None

        self.time_handlers = {
            self.DURATION_TYPE: self.do_duration,
            self.INSTANT_TYPE: self.do_instant,
            self.LOCAL_DATE_TYPE: self.do_local_date,
            self.LOCAL_DATE_TIME_TYPE: self.do_local_date_time,
            self.LOCAL_TIME_TYPE: self.do_local_time,
            self.ZONE_DATE_TIME_TYPE: self.do_zoned_date_time,
            self.ZONE_OFFSET_TYPE: self.do_zone_offset,
            self.ZONE_REGION_TYPE: self.do_zone_region,
            self.OFFSET_TIME_TYPE: self.do_offset_time,
            self.OFFSET_DATE_TIME_TYPE: self.do_offset_date_time,
            self.YEAR_TYPE: self.do_year,
            self.YEAR_MONTH_TYPE: self.do_year_month,
            self.MONTH_DAY_TYPE: self.do_month_day,
            self.PERIOD_TYPE: self.do_period,
        }

    def __str__(self):
        return (
            "JavaTime(type=0x{s.type}, "
            "year={s.year}, month={s.month}, day={s.day}, "
            "hour={s.hour}, minute={s.minute}, second={s.second}, "
            "nano={s.nano}, offset={s.offset}, zone={s.zone})"
        ).format(s=self)

    def load_from_blockdata(self, reader, indent=0):
        """
        Ignore the SC_BLOCK_DATA flag
        """
        return True

    def load_from_instance(self, instance, indent=0):
        # type: (JavaInstance, int) -> bool
        """
        Load content from a parsed instance object
        """
        # Lists have their content in there annotations
        for cd, annotations in instance.annotations.items():
            if cd.name == self.HANDLED_CLASSES:
                # Convert back annotations to bytes
                # latin-1 is used to ensure that bytes are kept as is
                content = to_bytes(annotations[0].data, "latin1")
                (self.type,), content = read(content, ">b")

                try:
                    self.time_handlers[self.type](content)
                except KeyError as ex:
                    log_error("Unhandled kind of time: {}".format(ex))

                return True

        return False

    def do_duration(self, data):
        (self.second, self.nano), data = read(data, ">qi")
        return data

    def do_instant(self, data):
        (self.second, self.nano), data = read(data, ">qi")
        return data

    def do_local_date(self, data):
        (self.year, self.month, self.day), data = read(data, ">ibb")
        return data

    def do_local_time(self, data):
        (hour,), data = read(data, ">b")
        minute = 0
        second = 0
        nano = 0

        if hour < 0:
            hour = ~hour
        else:
            (minute,), data = read(data, ">b")
            if minute < 0:
                minute = ~minute
            else:
                (second,), data = read(data, ">b")
                if second < 0:
                    second = ~second
                else:
                    (nano,), data = read(data, ">i")

        self.hour = hour
        self.minute = minute
        self.second = second
        self.nano = nano
        return data

    def do_local_date_time(self, data):
        data = self.do_local_date(data)
        data = self.do_local_time(data)
        return data

    def do_zoned_date_time(self, data):
        data = self.do_local_date_time(data)
        data = self.do_zone_offset(data)
        data = self.do_zone_region(data)
        return data

    def do_zone_offset(self, data):
        (offset_byte,), data = read(data, ">b")
        if offset_byte == 127:
            (self.offset,), data = read(data, ">i")
        else:
            self.offset = offset_byte * 900
        return data

    def do_zone_region(self, data):
        self.zone, data = read_string(data)
        return data

    def do_offset_time(self, data):
        data = self.do_local_time(data)
        data = self.do_zone_offset(data)
        return data

    def do_offset_date_time(self, data):
        data = self.do_local_date_time(data)
        data = self.do_zone_offset(data)
        return data

    def do_year(self, data):
        (self.year,), data = read(data, ">i")
        return data

    def do_year_month(self, data):
        (self.year, self.month), data = read(data, ">ib")
        return data

    def do_month_day(self, data):
        (self.month, self.day), data = read(data, ">bb")
        return data

    def do_period(self, data):
        (self.year, self.month, self.day), data = read(data, ">iii")
        return data


class DefaultObjectTransformer:

    KNOWN_TRANSFORMERS = (
        JavaBool,
        JavaInt,
        JavaList,
        JavaMap,
        JavaLinkedHashMap,
        JavaSet,
        JavaTreeSet,
        JavaTime,
    )

    def __init__(self):
        # Construct the link: Java class name -> Python transformer
        self._type_mapper = {}
        for transformer_class in self.KNOWN_TRANSFORMERS:
            handled_classes = transformer_class.HANDLED_CLASSES
            if isinstance(handled_classes, str):
                # Single class handled
                self._type_mapper[handled_classes] = transformer_class
            else:
                # Multiple classes handled
                for class_name in transformer_class.HANDLED_CLASSES:
                    self._type_mapper[class_name] = transformer_class

    def create(self, classdesc):
        # type: (JavaClassDesc) -> JavaInstance
        """
        Transforms a parsed Java object into a Python object

        :param classdesc: The description of a Java class
        :return: The Python form of the object, or the original JavaObject
        """
        try:
            mapped_type = self._type_mapper[classdesc.name]
        except KeyError:
            # Return None if not handled
            return None
        else:
            log_debug("---")
            log_debug(classdesc.name)
            log_debug("---")

            java_object = mapped_type()
            java_object.classdesc = classdesc

            log_debug(">>> java_object: {0}".format(java_object))
            return java_object