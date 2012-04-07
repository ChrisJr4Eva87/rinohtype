
from collections import OrderedDict
from io import BytesIO, SEEK_CUR, SEEK_END
import re, struct

from . import cos


class PDFReader(cos.Document):
    DICT_BEGIN = b'<<'
    DICT_END = b'>>'
    STRING_BEGIN = b'('
    STRING_END = b')'
    ARRAY_BEGIN = b'['
    ARRAY_END = b']'
    HEXSTRING_BEGIN = b'<'
    HEXSTRING_END = b'>'
    NAME_BEGIN = b'/'
    COMMENT_BEGIN = b'%'

    def __init__(self, file_or_filename):
        try:
            self.file = open(file_or_filename, 'rb')
        except NotImplementedError:
            self.file = file_or_filename

        self.indirect_objects = {}
        xref_offset = self.find_xref_offset()
        self.xref = self.parse_xref_tables(xref_offset)
        self.trailer = self.parse_trailer()
        self.root = self.trailer['Root']

    def jump_to_next_line(self):
        while True:
            char = self.file.read(1)
            if char == b'\n':
                break
            elif char == b'\r':
                next_char = self.file.read(1)
                if next_char != b'\n':
                    self.file.seek(-1, SEEK_CUR)
                break

    whitespace = b'\0\t\n\f\r '
    delimiters = b'()<>[]{}/%'

    def eat_whitespace(self):
        while True:
            char = self.file.read(1)
            if char not in self.whitespace:
                self.file.seek(-1, SEEK_CUR)
                break

    def next_token(self):
        token = self.file.read(1)
        if token in (self.HEXSTRING_BEGIN, self.HEXSTRING_END):
            # check for dict begin/end
            char = self.file.read(1)
            if char == token:
                token += char
            else:
                self.file.seek(-1, SEEK_CUR)
        elif token in self.delimiters + self.whitespace:
            pass
        else:
            while True:
                char = self.file.read(1)
                if char in self.delimiters + self.whitespace:
                    self.file.seek(-1, SEEK_CUR)
                    break
                token += char
        return token

    def next_item(self):
        self.eat_whitespace()
        restore_pos = self.file.tell()
        token = self.next_token()
        if token == self.STRING_BEGIN:
            item = self.read_string()
        elif token == self.HEXSTRING_BEGIN:
            item = self.read_hex_string()
        elif token == self.ARRAY_BEGIN:
            item = self.read_array()
        elif token == self.NAME_BEGIN:
            item = self.read_name()
        elif token == self.DICT_BEGIN:
            item = self.read_dictionary()
            self.eat_whitespace()
            dict_pos = self.file.tell()
            if self.next_token() == b'stream':
                item = self.read_stream()
            else:
                self.file.seek(dict_pos)
        elif token == b'true':
            item = cos.Boolean(True)
        elif token == b'false':
            item = cos.Boolean(False)
        elif token == b'null':
            item = cos.Null()
        else:
            # number or indirect reference
            self.file.seek(restore_pos)
            item = self.read_number()
            restore_pos = self.file.tell()
            if isinstance(item, cos.Integer):
                try:
                    generation = self.read_number()
                    self.eat_whitespace()
                    r = self.next_token()
                    if isinstance(generation, cos.Integer) and r == b'R':
                        item = cos.Reference(self, item, generation)
                    else:
                        raise ValueError
                except ValueError:
                    self.file.seek(restore_pos)
        return item

    def peek(self):
        restore_pos = self.file.tell()
        print(self.file.read(20))
        self.file.seek(restore_pos)

    def read_array(self):
        array = cos.Array()
        while True:
            self.eat_whitespace()
            token = self.file.read(1)
            if token == self.ARRAY_END:
                break
            self.file.seek(-1, SEEK_CUR)
            item = self.next_item()
            array.append(item)
        return array

    def read_hex_string(self):
        string = b''
        while True:
            self.eat_whitespace()
            char = self.file.read(1)
            if char == self.HEXSTRING_END:
                break
            string += char
        if len(string) % 2 > 0:
            string += b'0'
        return cos.Integer(string, 16)

    re_name_escape = re.compile(r'#\d\d')

    def read_name(self):
        name = ''
        while True:
            char = self.file.read(1)
            if char in self.delimiters + self.whitespace:
                self.file.seek(-1, SEEK_CUR)
                break
            name += char.decode('utf_8')
        for group in set(self.re_name_escape.findall(name)):
            number = int(group[1:], 16)
            name.replace(group, chr(number))
        return cos.Name(name)

    def read_dictionary(self):
        dictionary = cos.Dictionary()
        while True:
            self.eat_whitespace()
            token = self.next_token()
            if token == self.DICT_END:
                break
            key, value = self.read_name(), self.next_item()
            dictionary[key.name] = value
        return dictionary

    def read_stream(self):
        stream = cos.Stream(self)

    newline_chars = b'\n\r'
    escape_chars = b'nrtbf()\\'

    def read_string(self):
        string = b''
        escape = False
        while True:
            char = self.file.read(1)
            if escape:
                if char in self.escape_chars:
                    string += char
                elif char == b'\n':
                    pass
                elif char == b'\r' and self.file.read(1) != '\n':
                    self.file.seek(-1, SEEK_CUR)
                elif char.isdigit():
                    for i in range(2):
                        extra = self.file.read(1)
                        if extra.isdigit():
                            char += extra
                        else:
                            self.file.seek(-1, SEEK_CUR)
                            break
                    sttring += struct.pack('B', int(char, 8))
                else:
                    string += b'\\' + char
                escape = False
            elif char == b'\\':
                escape = True
            elif char == self.STRING_END:
                break
            else:
                string += char
        return cos.String(string.decode('utf_8'))

    def read_number(self):
        self.eat_whitespace()
        number = b''
        while True:
            char = self.file.read(1)
            if char not in b'+-.0123456789':
                self.file.seek(-1, SEEK_CUR)
                break
            number += char
        try:
            number = cos.Integer(number)
        except ValueError:
            number = cos.Real(number)
        return number

    def parse_trailer(self):
        assert self.next_token() == b'trailer'
        self.jump_to_next_line()
        trailer_dict = self.next_item()
        return trailer_dict
##/Size: (Required; must not be an indirect reference) The total number of entries in the file's
##cross-reference table, as defined by the combination of the original section and all
##update sections. Equivalently, this value is 1 greater than the highest object number
##used in the file.
##Note: Any object in a cross-reference section whose number is greater than this value is
##ignored and considered missing.

    def get_indirect_object(self, identifier, generation):
        id_gen = (identifier, generation)
        try:
            item = self.indirect_objects[id_gen]
        except KeyError:
            address = self.xref[id_gen]
            item = self.parse_indirect_object(address)
            self.indirect_objects[id_gen] = item
        return item

    def parse_indirect_object(self, address):
        # save file state
        restore_pos = self.file.tell()
        self.file.seek(address)
        self.read_number()  # identifier
        self.eat_whitespace()
        self.read_number()  # generation
        self.eat_whitespace()
        self.next_token()   # 'obj'
        self.eat_whitespace()
        item = self.next_item()
        self.file.seek(restore_pos)
        return item

    def parse_xref_tables(self, offset):
        xref = {}
        self.file.seek(offset)
        assert self.next_token() == b'xref'
        self.jump_to_next_line()
        while True:
            try:
                obj_id, entries = self.read_number(), self.read_number()
            except ValueError:
                break
            self.jump_to_next_line()
            for i in range(entries):
                line = self.file.read(20)
                if line[17] == ord(b'n'):
                    address, generation = int(line[:10]), int(line[11:16])
                    xref[obj_id, generation] = address
                obj_id += 1
        return xref

    def find_xref_offset(self):
        self.file.seek(0, SEEK_END)
        offset = self.file.tell() - len('%%EOF')
        while True:
            self.file.seek(offset)
            value = self.file.read(len('startxref'))
            if value == b'startxref':
                self.jump_to_next_line()
                xref_offset = self.read_number()
                self.jump_to_next_line()
                if self.file.read(5) != b'%%EOF':
                    raise ValueError('Invalid PDF file: missing %%EOF')
                break
            offset -= 1
        return xref_offset
