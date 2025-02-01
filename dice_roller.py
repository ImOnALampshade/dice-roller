#!/usr/bin/python3

from cursor import cursor, rollback_if_false, ParserError
import random
import re
import sys

from collections.abc import Callable
from typing import Optional

# Colors we output to the terminal.
class term_colors:
    DUMP_ROLL_TEXT = "\033[93m"
    DUMP_ROLL_VALUES = "\033[96m"
    DUMP_ROLL_CONST = "\033[95m"
    DUMP_ROLL_CALC = "\033[92m"
    TOTAL_VALUE = "\033[92m"
    ERROR_ARROW = ""
    ERROR_TEXT = "\033[91m"
    RESET = "\033[0m"


# A regex to match decimal integer numbers
int_regex = re.compile(r"[1-9][0-9]*")

# A regex to match a "2d6" style expression
n_d_k_regex = re.compile(
    r"(?P<dice_count>[1-9][0-9]*)\s*[dD]\s*(?P<die_size>[1-9][0-9]*)"
)


class roll_result:
    """
    The result of a dice roll
    """

    def __init__(
        self, result: list[int], header: str, inner_results: list["roll_result"]
    ) -> None:
        """
        Args:
          result: The list of numbers in this result
          header: The title of this stage of the roll result tree
          inner_results: The actual roll_result objects describing the integer result array
        """
        self.__r = result
        self.__hdr = header
        self.__inner = inner_results

    @property
    def values(self) -> list[int]:
        return self.__r

    @property
    def dump_mode(self):
        # Based on our header, change the color of our output.
        # TODO: better way to do this is to have the color defined as part of our constructor.
        if self.__hdr == "const":
            return term_colors.DUMP_ROLL_CONST
        elif n_d_k_regex.fullmatch(self.__hdr) is not None:
            return term_colors.DUMP_ROLL_VALUES
        else:
            return term_colors.DUMP_ROLL_CALC

    def dump(self, *, indent="", add_indent="    "):
        """
        Dumps the audit of this roll result to stdout.

        Args:
          indent: The initial indentation string. Defaults to an empty string for no indentation at the first level.
          add_indent: What to add to the indentation string for each indentation. Defaults to 4 spaces.
        """
        r = ", ".join(f"{self.dump_mode}{i}{term_colors.RESET}" for i in self.__r)
        print(
            f"{indent}{term_colors.DUMP_ROLL_TEXT}{self.__hdr}{term_colors.RESET} : {r}"
        )
        for inner in self.__inner:
            inner.dump(indent=indent + add_indent, add_indent=add_indent)


class roller_base:
    """
    The base class for dice roller AST nodes.
    """

    def roll(self) -> roll_result:
        """
        The base roller function for all dice roller AST nodes.
        """
        raise NotImplementedError


class roller_constant(roller_base):
    """
    A dice roll representing a const value, usually a modifier.
    """

    def __init__(self, c: int) -> None:
        """
        Args:
          c: The integer constant.
        """
        self.__constant = c

    def roll(self) -> roll_result:
        return roll_result([self.__constant], "const", [])


class roller_die(roller_base):
    """
    A dice roll that is representative of a 2d6 style expression. Result will be the simulated dice roll.
    """

    def __init__(self, count: int, die: int) -> None:
        """

        Args:
          count: The number of dice to roll.
          die: The size die to roll.
        """
        self.__c = count
        self.__d = die

    def roll(self) -> roll_result:
        l = [random.randint(1, self.__d) for _ in range(self.__c)]
        return roll_result(sorted(l), f"{self.__c}d{self.__d}", [])


class roller_unary_operator(roller_base):
    """
    A unary operator node in the dice roller AST
    """

    def __init__(
        self, inner: roller_base, op: Callable[[list[int]], list[int]], title: str
    ) -> None:
        """
        Args:
          inner : The AST node for the right hand argument
          op:
            The operation method, which is a function that takes the rolls from the value this operator is applied
            to, and returns the rolls that the operator results in.
          title: A string representing the name of this operator, to use when outputting an audit.
        """
        self.__i = inner
        self.__c = op
        self.__t = title

    def roll(self) -> roll_result:
        r = self.__i.roll()
        result = self.__c(r.values)
        return roll_result(result, self.__t, [r])


class roller_binary_op(roller_base):
    """
    A binary operator node in the dice roller AST.
    That is, an operator that takes two rolls and returns a single roll.
    """

    def __init__(
        self,
        lhs: roller_base,
        rhs: roller_base,
        op: Callable[[list[int], list[int]], list[int]],
        op_str: str,
    ):
        """
        Args:
          rhs : The AST node for the right hand argument
          lhs : The AST node for the left hand argument
          op:
            The operation method, which is a function that takes the rolls from rhs and lhs (as `list[int]`'s)
            and returns the result of the binary operation as a single list[int]
          op_str: A string representing the name of this operator, to use when outputting an audit.
        """
        self.__l = lhs
        self.__r = rhs
        self.__op = op
        self.__op_str = op_str

    def roll(self) -> roll_result:
        l = self.__l.roll()
        r = self.__r.roll()
        result = self.__op(l.values, r.values)
        return roll_result(result, self.__op_str, [l, r])


class roller_cursor(cursor):
    def __init__(self, line: str):
        """
        Initializes the dice roll parser with a line of text.

        Args:
          line: The line of text.
        """
        super(roller_cursor, self).__init__(line)

    @rollback_if_false
    def accept_value(self) -> Optional[roller_base]:
        """
          Accepts an expression resulting in a single value.
        """
        if self.accept_punctuation("("):
            roll = self.accept_roll()
            self.expect_punctuation(")")
            return roll
        else:
            count = self.accept_regex_str(int_regex)
            if count is None:
                return None
            count = int(count)
            if self.accept_punctuation("d"):
                die = self.expect_regex_str(int_regex, "integer")
                die = int(die)
                return roller_die(count, die)
            else:
                return roller_constant(count)

    @rollback_if_false
    def accept_operator(self) -> Optional[roller_base]:
        """
          Accepts the use of a unary operator. Descends into checking for a value.
        """
        # Assign our operator based on the function
        if self.accept_keyword("max"):
            op = lambda s: [s[0] if len(s) == 1 else max(*s)]
            op_name = "max"
        elif self.accept_keyword("min"):
            op = lambda s: [s[0] if len(s) == 1 else min(*s)]
            op_name = "min"
        elif self.accept_keyword("sum"):
            op = lambda s: [sum(s)]
            op_name = "sum"
        elif self.accept_keyword("top"):
            count = self.expect_regex_str(int_regex, "integer")
            count = int(count)
            op = lambda s: s[-count:]
            op_name = f"top {count}"
        elif self.accept_keyword("bottom"):
            count = self.expect_regex_str(int_regex, "integer")
            count = int(count)
            op = lambda s: s[0:count]
            op_name = f"bottom {count}"
        elif self.accept_keyword("count"):
            count = self.expect_regex_str(int_regex, "integer")
            count = int(count)
            op = lambda s: [sum(1 for i in s if i == count)]
            op_name = f"count {count}"
        else:
            # Default case - not a function, try parsing just value
            return self.accept_value()

        roller = self.accept_value()
        if not roller:
            return None
        return roller_unary_operator(roller, op, op_name)

    @rollback_if_false
    def accept_roll(self) -> Optional[roller_base]:
        """
          Accepts an entire roll expression as
        """
        op1 = self.accept_operator()

        if self.accept_punctuation("+"):
            op2 = self.expect_roll()
            return roller_binary_op(
                op1, op2, (lambda l, r: [int(sum(l) + sum(r))]), "Sum"
            )
        elif self.accept_punctuation("-"):
            op2 = self.expect_roll()
            return roller_binary_op(
                op1, op2, (lambda l, r: [int(sum(l) - sum(r))]), "Subtract"
            )
        elif self.accept_punctuation("*"):
            op2 = self.expect_roll()
            return roller_binary_op(
                op1, op2, (lambda l, r: [int(sum(l) * sum(r))]), "Multiply"
            )
        elif self.accept_punctuation("/"):
            op2 = self.expect_roll()
            return roller_binary_op(
                op1, op2, (lambda l, r: [int(sum(l) / sum(r))]), "Divide"
            )
        elif self.accept_punctuation(","):
            op2 = self.expect_roll()
            return roller_binary_op(op1, op2, (lambda l, r: sorted(l + r)), "Concat")
        else:
            return op1

    def expect_roll(self) -> roller_base:
        """
        Expects a roll from the input string, and raise a parser error if none was parsed.
        """
        roll = self.accept_roll()
        if not roll:
            raise self.create_parser_error("expected a roll")
        return roll

    def expect_line(self) -> roller_base:
        """
        The only accept/expect method intended to be called externally.
        Raises a parser error on failure to parse the text.

        Returns:
          the parsed AST node.

        """
        roll = self.expect_roll()

        # Check for a ; to show the roll string is complete (everything after that is considered a comment)
        if not self.at_eof and not self.accept_punctuation(";"):
            raise self.create_parser_error("Failed to parse input")

        self.set_eof()

        return roll


if __name__ == '__main__':
  last_line = ""
  last_result = None
  prompt_str = "dice> "

  while True:
      # Grab a line of text from stdin
      line = input(prompt_str)

      # Check for one-liners
      if line == "q":
          break
      elif line == "c":
          print("\033[2J\033[H", end="")
          continue
      elif line == "?":
          if last_result != None:
              last_result.dump()
          else:
              print('No last result to print!', file=sys.stderr)
          continue
      elif line == "":
          line = last_line
      else:
          last_line = line

      c = roller_cursor(line)
      try:
          roller = c.expect_line()
          result = roller.roll()
          last_result = result
          print(f"{term_colors.TOTAL_VALUE}{sum(result.values)}{term_colors.RESET}")
      except ParserError as e:
          indent = ' ' * len(prompt_str)
          arrow = f"{term_colors.ERROR_ARROW}{'-' * e.position}^"
          text = f"{term_colors.ERROR_TEXT}{e}{term_colors.RESET}"
          print(
              f'{indent}{arrow} {text}',
              file=sys.stderr,
          )
