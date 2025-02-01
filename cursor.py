import re
import string
from typing import Optional

identifier_chars = set(string.ascii_letters + string.digits + '_')

class ParserError(Exception):
  def __init__(self, s : str, message: str, pos : int) -> None:
    self.__msg = message
    self.__str = s
    self.__pos = pos

  def __str__(self) -> str:
    return self.__msg

  @property
  def position(self) -> int:
    return self.__pos

class cursor:
  def __init__(self, contents: str) -> None:
    self.__contents = contents
    self.__pos = 0

    self.__advance_to_non_whitespace()

  def read_to_newline(self) -> str:
    eol = self.__contents.find('\n', self.__pos)

    if eol == -1:
      # Couldn't find a \n in the string starting from the current position
      # This means the entire remainder of the contents are on 1 line, so return
      # that and place our cursor at eof
      start = self.__pos
      self.__pos = len(self.__contents)
      return self.__contents[start:].rstrip()
    else:
      # Just move to the cursor to the end of the line and return the line
      start = self.__pos
      self.__pos = eol
      self.__advance_to_non_whitespace()
      return self.__contents[start:eol].rstrip()

  def match_substr(self, match : re.Match) -> str:
    return self.__contents[match.start() : match.end()]

  def accept_keyword(self, keyword: str) -> bool:
    end_pos = self.__pos + len(keyword)

    # check that the cursor now points to our search string
    if keyword == self.__contents[self.__pos:end_pos]:
      # If we matched, verify that the next is not an identifier character,
      # which would mean we have something like 'inter_whatever_foo', which isn't the
      # int keyword, but instead is an identifier that starts with a keyword
      next_char = self.__contents[end_pos]
      if next_char in identifier_chars:
        return False
      else:
        self.__pos = end_pos
        self.__advance_to_non_whitespace()
        return True

    else:
      return False

  def accept_punctuation(self, string: str) -> bool:
    end_pos = self.__pos + len(string)

    # check that the cursor now points to our search string
    if string == self.__contents[self.__pos:end_pos]:
      self.__pos = end_pos
      self.__advance_to_non_whitespace()
      return True

    else:
      return False

  def accept_regex(self, regex: re.Pattern) -> Optional[re.Match]:
    # Try to match at the current cursor position
    m = regex.match(self.__contents, pos=self.__pos)

    if m is None:
      return None
    else:
      # Got a match, set our cursor to the end of the expression
      self.__pos = m.end()
      self.__advance_to_non_whitespace()
      return m

  def accept_regex_str(self, regex : re.Pattern) -> Optional[str]:
    match = self.accept_regex(regex)
    if match is None:
      return None
    else:
      return self.match_substr(match)

  def expect_keyword(self, string: str) -> None:
    if not self.accept_keyword(string):
      raise self.create_parser_error(f'expected keyword `{string}`')

  def expect_punctuation(self, string: str) -> None:
    if not self.accept_punctuation(string):
      got_char = self.__contents[self.__pos] if self.__pos < len(self.__contents) else '<eof>'
      raise self.create_parser_error(f'expected punctuation `{string}`, got `{got_char}`')

  def expect_regex(self, regex: re.Pattern, description : str = 'regex') -> re.Match:
    match = self.accept_regex(regex)
    if match is None:
      raise self.create_parser_error(f'expected {description}')
    else:
      return match

  def expect_regex_str(self, regex = re.Pattern, description : str = 'regex') -> str:
    match = self.expect_regex(regex, description)
    return self.match_substr(match)

  def set_rollback(self) -> int:
    return self.__pos

  def rollback_to(self, pos: int) -> None:
    self.__pos = pos

  def create_parser_error(self, msg: str) -> ParserError:
    return ParserError(self.__contents, msg, self.__pos)

  @property
  def at_eof(self) -> bool:
    return self.__pos == len(self.__contents)

  def set_eof(self):
    self.__pos = len(self.__contents)

  @property
  def position(self) -> int:
    return self.__pos

  def __advance_to_non_whitespace(self) -> None:
    while not self.at_eof and self.__contents[self.__pos].isspace():
      self.__pos += 1


def rollback_if_false(meth):
  def inner(self: cursor, *args, **kwargs):
    rollback = self.set_rollback()
    result = meth(self, *args, **kwargs)
    if not result:
      self.rollback_to(rollback)
    return result
  return inner