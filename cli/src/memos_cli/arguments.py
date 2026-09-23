"""Command construction, discovery, and input parsing."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__, registry
from .errors import ClientError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ClientError(message)


def globals_parser():
    parser = Parser(add_help=False)
    parser.add_argument("--json", dest="format", action="store_const", const="json")
    parser.add_argument("--text", dest="format", action="store_const", const="text")
    parser.add_argument("--connection", help="saved hosted connection")
    parser.add_argument("--url", help="override hosted URL")
    parser.add_argument("--timeout", type=float, default=15)
    return parser


def convert(kind):
    if kind == "integer":
        return int
    if kind == "number":
        return float
    if kind in {"object", "array"}:
        return json.loads
    return str


def field(parser, name, schema, *, positional=False, dest=None):
    kind = registry.simple_type(schema)
    kwargs = {"help": schema.get("description") or name.replace("_", " ")}
    if positional:
        parser.add_argument(name, nargs="?", default=argparse.SUPPRESS, **kwargs)
        return
    flag = "--" + name.replace("_", "-")
    kwargs.update(dest=dest or name, default=argparse.SUPPRESS)
    if kind == "boolean":
        kwargs["action"] = argparse.BooleanOptionalAction
    else:
        kwargs["type"] = convert(kind)
        kwargs["metavar"] = "JSON" if kind in {"array", "object"} else None
    parser.add_argument(flag, **kwargs)


def parser_tree():
    root = Parser(
        prog="memos",
        description="Hosted memory for people and agents. Start with memos setup.",
        epilog="Global options: --json, --text (output), --connection NAME, --url URL, --timeout SECONDS. Use commands --json to discover operations.",
    )
    root.add_argument("--version", action="version", version=__version__)
    groups = {(): root}
    subparsers = {}

    def leaf(words, **kwargs):
        path = ()
        for word in words:
            if path not in subparsers:
                subparsers[path] = groups[path].add_subparsers(
                    required=True, dest=f"command_{len(path)}"
                )
            next_path = (*path, word)
            if next_path not in groups:
                groups[next_path] = subparsers[path].add_parser(
                    word, **(kwargs if word == words[-1] else {})
                )
            path = next_path
        return groups[path]

    document = registry.spec()
    for command in [*registry.ROUTES, *registry.ALIASES]:
        op = registry.operation(command, document)
        parser = leaf(
            command.split(), help=op["description"].split("\n")[0], description=op["description"]
        )
        parser.set_defaults(handler="api", operation=op)
        used = set()
        for parameter in op["parameters"]:
            name = parameter["name"]
            field(parser, name, parameter["schema"], positional=parameter["in"] == "path")
            used.add(name)
        positional = {"remember": "text", "search": "query"}.get(command)
        for name, schema in op["body"].get("properties", {}).items():
            if name == positional:
                field(parser, name, schema, positional=True)
            else:
                # --text is also a global output switch; global parsing only consumes
                # it when it has no value (handled by split_globals).
                field(parser, name, schema, dest="body_" + name if name in used else name)
        parser.add_argument("--data", help="JSON body, @file, or - for stdin")
        parser.add_argument("--output", help="write response or download to a file")
        parser.add_argument("--wait", nargs="?", const=60, type=float, default=0, metavar="SECONDS")
        if any(p["name"] == "offset" for p in op["parameters"]):
            parser.add_argument(
                "--all", action="store_true", help="fetch all pages within the wait budget"
            )

    setup = leaf(["setup"], help="connect and log in once")
    setup.set_defaults(handler="setup")
    setup.add_argument("--name", default="default")
    setup.add_argument("--api-key-file")
    setup.add_argument("--password-file")
    setup.add_argument("--handle")
    from .agents import targets

    setup.add_argument(
        "--agents", nargs="*", type=targets, metavar="AGENT", help="claude, hermes or codex"
    )
    for cmd in ("list", "use", "remove"):
        p = leaf(["connections", cmd])
        p.set_defaults(handler="connections", action=cmd)
        if cmd != "list":
            p.add_argument("name")
    p = leaf(["status"], help="check connection, identity, and service readiness")
    p.set_defaults(handler="status")
    p = leaf(["commands"], help="discover all capabilities")
    p.set_defaults(handler="commands")
    p = leaf(["schema"], help="show command arguments and JSON schema")
    p.add_argument("name", nargs="+")
    p.set_defaults(handler="schema")
    from .agents import add_parser as agents_parser
    from .server import add_parser as server_parser

    agents_parser(leaf)
    server_parser(leaf)
    return root


def split_globals(argv):
    # Global flags work before or after the command, without stealing --text TEXT
    # from memory writes or --name from operation payloads.
    global_args, local_args = [], []
    i = 0
    valued = {"--connection", "--url", "--timeout"}
    while i < len(argv):
        argument = argv[i]
        if argument == "--":
            local_args.extend(argv[i:])
            break
        key = argument.split("=", 1)[0]
        if key in valued:
            global_args.append(argument)
            if "=" not in argument:
                if i + 1 == len(argv):
                    raise ClientError(f"{argument} needs a value")
                i += 1
                global_args.append(argv[i])
        elif argument == "--json" or (
            argument == "--text"
            and (not local_args or i + 1 == len(argv) or argv[i + 1].startswith("--"))
        ):
            global_args.append(argument)
        else:
            local_args.append(argument)
        i += 1
    return global_args, local_args


def read_value(value):
    if value == "-":
        return sys.stdin.read(2 * 1024 * 1024 + 1)
    if value.startswith("@"):
        with Path(value[1:]).expanduser().open() as stream:
            return stream.read(2 * 1024 * 1024 + 1)
    return value


def local_schemas():
    """Describe non-API commands from the parser that actually accepts them."""
    result = {}

    def walk(parser, path=()):
        if parser.get_default("handler") and parser.get_default("handler") != "api":
            arguments = []
            for action in parser._actions:
                if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
                    continue
                arguments.append(
                    {
                        "name": action.dest,
                        "flags": action.option_strings,
                        "required": action.required,
                        "help": action.help,
                        "choices": list(action.choices) if action.choices is not None else None,
                        "nargs": action.nargs,
                    }
                )
            result[" ".join(path)] = {"command": " ".join(path), "arguments": arguments}
        for action in parser._actions:
            if isinstance(action, argparse._SubParsersAction):
                for name, child in action.choices.items():
                    walk(child, (*path, name))

    walk(parser_tree())
    return result


def referenced_definitions(value, document):
    definitions = {}

    def visit(item):
        if isinstance(item, dict):
            if "$ref" in item:
                name = item["$ref"].rsplit("/", 1)[-1]
                if name not in definitions:
                    definitions[name] = document["components"]["schemas"][name]
                    visit(definitions[name])
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return definitions
