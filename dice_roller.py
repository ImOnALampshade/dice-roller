#!/usr/bin/python3

from cursor import cursor, rollback_if_false, ParserError
import random
import re
import sys

class term_colors:
  DUMP_ROLL_TEXT = '\033[93m'
  DUMP_ROLL_VALUES = '\033[96m'
  DUMP_ROLL_CONST = '\033[95m'
  DUMP_ROLL_CALC = '\033[92m'
  TOTAL_VALUE = '\033[92m'
  ERROR_ARROW = ''
  ERROR_TEXT = '\033[91m'
  RESET = '\033[0m'

int_regex = re.compile(r'[1-9][0-9]*')
n_d_k_regex = re.compile(r'(?P<dice_count>[1-9][0-9]*)\s*[dD]\s*(?P<die_size>[1-9][0-9]*)')

class roll_result:
  def __init__(self, result : list[int], header : str, inner_results : list) -> None:
    self.__r = result
    self.__hdr = header
    self.__inner = inner_results

  @property
  def values(self):
    return self.__r

  @property
  def dump_mode(self):
    if self.__hdr == 'const':
      return term_colors.DUMP_ROLL_CONST
    elif n_d_k_regex.fullmatch(self.__hdr) is not None:
      return term_colors.DUMP_ROLL_VALUES
    else:
      return term_colors.DUMP_ROLL_CALC

  def dump(self, indent='', add_indent='    '):
    r = ', '.join(f'{self.dump_mode}{i}{term_colors.RESET}' for i in self.__r)
    print(f'{indent}{term_colors.DUMP_ROLL_TEXT}{self.__hdr}{term_colors.RESET} : {r}')
    for inner in self.__inner:
      inner.dump(indent + add_indent, add_indent)

class roller_base:
  def roll(self) -> roll_result:
    raise NotImplementedError

class roller_constant(roller_base):
  def __init__(self, c : int) -> None:
    self.__constant = c

  def roll(self) -> roll_result:
    return roll_result([ self.__constant ], "const", [])

class roller_die(roller_base):
  def __init__(self, count : int, die : int) -> None:
    self.__c = count
    self.__d = die

  def roll(self) -> roll_result:
    l = [ random.randint(1, self.__d) for _ in range(self.__c) ]
    return roll_result(sorted(l), f"{self.__c}d{self.__d}", [])

class roller_unary_operator(roller_base):
  def __init__(self, inner : roller_base, op, title : str) -> None:
    self.__i = inner
    self.__c = op
    self.__t = title

  def roll(self) -> roll_result:
    r = self.__i.roll()
    result = self.__c(r.values)
    return roll_result(result, self.__t, [ r ])

class roller_binary_op(roller_base):
  def __init__(self, lhs : roller_base, rhs : roller_base, op, op_str : str):
    self.__l = lhs
    self.__r = rhs
    self.__op = op
    self.__op_str = op_str

  def roll(self):
    l = self.__l.roll()
    r = self.__r.roll()
    result = self.__op(l.values, r.values)
    return roll_result(result, self.__op_str, [ l, r ])

class roller_cursor(cursor):
  def __init__(self, line):
    super(roller_cursor, self).__init__(line)

  @rollback_if_false
  def accept_value(self):
    if self.accept_punctuation('('):
      roll = self.accept_roll()
      self.expect_punctuation(')')
      return roll
    else:
      count = self.accept_regex_str(int_regex)
      if count is None: return None
      count = int(count)
      if self.accept_punctuation('d'):
        die = self.expect_regex_str(int_regex, 'integer')
        die = int(die)
        return roller_die(count, die)
      else:
        return roller_constant(count)

  @rollback_if_false
  def accept_operator(self):
    # Assign our operator based on the function
    if self.accept_keyword('max'):
      op = lambda s: [ s[0] if len(s) == 1 else max(*s) ]
      op_name = 'max'
    elif self.accept_keyword('min'):
      op = lambda s: [ s[0] if len(s) == 1 else min(*s) ]
      op_name = 'min'
    elif self.accept_keyword('sum'):
      op = lambda s: [ sum(s) ]
      op_name = 'sum'
    elif self.accept_keyword('top'):
      count = self.expect_regex_str(int_regex, 'integer')
      count = int(count)
      op = lambda s: s[-count:]
      op_name = f'top {count}'
    elif self.accept_keyword('bottom'):
      count = self.expect_regex_str(int_regex, 'integer')
      count = int(count)
      op = lambda s: s[0:count]
      op_name = f'bottom {count}'
    elif self.accept_keyword('count'):
      count = self.expect_regex_str(int_regex, 'integer')
      count = int(count)
      op = lambda s: [ sum(1 for i in s if i == count) ]
      op_name = f'count {count}'
    else:
      # Default case - not a function, try parsing just value
      return self.accept_value()

    roller = self.accept_value()
    if not roller:
      return None
    return roller_unary_operator(roller, op, op_name)

  @rollback_if_false
  def accept_roll(self):
    op1 = self.accept_operator()

    if self.accept_punctuation('+'):
      op2 = self.expect_roll()
      return roller_binary_op(op1, op2, (lambda l, r: [ int(sum(l) + sum(r)) ]), 'Sum')
    elif self.accept_punctuation('-'):
      op2 = self.expect_roll()
      return roller_binary_op(op1, op2, (lambda l, r: [ int(sum(l) - sum(r)) ]), 'Subtract')
    elif self.accept_punctuation('*'):
      op2 = self.expect_roll()
      return roller_binary_op(op1, op2, (lambda l, r: [ int(sum(l) * sum(r)) ]), 'Multiply')
    elif self.accept_punctuation('/'):
      op2 = self.expect_roll()
      return roller_binary_op(op1, op2, (lambda l, r: [ int(sum(l) / sum(r)) ]), 'Divide')
    elif self.accept_punctuation(','):
      op2 = self.expect_roll()
      return roller_binary_op(op1, op2, (lambda l, r: sorted(l + r)), 'Concat')
    else:
      return op1

  def expect_roll(self):
    roll = self.accept_roll()
    if not roll:
      raise self.create_parser_error('expected a roll')
    return roll

  def expect_line(self):
    roll = self.expect_roll()

    if not self.at_eof and not self.accept_punctuation(';'):
      raise self.create_parser_error('Failed to parse input')

    self.set_eof()

    return roll

last_line = ''
last_result = None
prompt_str = 'dice> '

while True:
  line = input(prompt_str)
  if line == 'q':
    break
  elif line == 'c':
    print('\033[2J\033[H', end = '')
    continue
  elif line == '?':
    if last_result != None:
      last_result.dump()
    continue
  elif line == '':
    line = last_line
  else:
    last_line = line

  c = roller_cursor(line)
  try:
    roller = c.expect_line()
    result = roller.roll()
    last_result = result
    print(f'{term_colors.TOTAL_VALUE}{sum(result.values)}{term_colors.RESET}')
  except ParserError as e:
    print(f"{' ' * len(prompt_str)}{term_colors.ERROR_ARROW}{'-' * e.position}^ {term_colors.ERROR_TEXT}{e}{term_colors.RESET}", file=sys.stderr)