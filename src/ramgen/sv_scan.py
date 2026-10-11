"""Small shared scanner for RAM declarations, retaining source offsets."""
import re

TOKEN_PATTERN = re.compile(
    r'^[ \t]*`define\b(?:[^\r\n]*\\\r?\n)*[^\r\n]*|'
    r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"|'
    r'\\[^\s]+|[a-zA-Z_$][\w$]*|[^\s]', re.MULTILINE)
IDENTIFIER = re.compile(r'(?:[a-zA-Z_$][\w$]*|\\[^\s]+)\Z')


def tokenize(text):
    return [match for match in TOKEN_PATTERN.finditer(text)
            if not match.group().lstrip().startswith(('//', '/*', '`define'))]


def matching_delimiters(tokens):
    closing, stack = {}, []
    pairs = {')': '(', ']': '[', '}': '{'}
    for idx, token in enumerate(tokens):
        value = token.group()
        if value in ('(', '[', '{'):
            stack.append((value, idx))
        elif value in pairs and stack and stack[-1][0] == pairs[value]:
            _, start = stack.pop()
            closing[start] = idx
    return closing


def mask_comments(text):
    def replace(match):
        value = match.group()
        return re.sub(r'[^\n]', ' ', value) if value.startswith(('//', '/*')) else value
    return TOKEN_PATTERN.sub(replace, text)


def named_connections(block):
    """Read .name(expression), preserving balanced nested expressions."""
    tokens = tokenize(block)
    closing = matching_delimiters(tokens)
    idx = 0
    while idx + 1 < len(tokens):
        if tokens[idx].group() != '.' or not IDENTIFIER.fullmatch(tokens[idx + 1].group()):
            idx += 1
            continue
        name = tokens[idx + 1].group()
        opening = idx + 2
        if opening < len(tokens) and tokens[opening].group() == '(' and opening in closing:
            end = closing[opening]
            yield name, block[tokens[opening].end():tokens[end].start()].strip()
            idx = end + 1
        else:
            # SystemVerilog shorthand .name is equivalent to .name(name).
            yield name, name
            idx = opening


def module_headers(tokens):
    for idx, token in enumerate(tokens):
        if token.group() == 'module':
            name_idx = idx + 1
            if name_idx < len(tokens) and tokens[name_idx].group() in ('automatic', 'static'):
                name_idx += 1
            if name_idx < len(tokens) and IDENTIFIER.fullmatch(tokens[name_idx].group()):
                yield idx, name_idx


def instance_declarations(text, tokens, closing, types):
    """Yield complete shared-type declarations with one or more instances.

    types is a predicate. Comments and strings remain opaque to matching;
    parameter/connection expressions are extracted from the original text.
    """
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if not types(token.group()):
            idx += 1
            continue
        cursor = idx + 1
        params = ''
        if cursor < len(tokens) and tokens[cursor].group() == '#':
            cursor += 1
            if cursor not in closing or tokens[cursor].group() != '(':
                idx += 1
                continue
            end = closing[cursor]
            params = text[tokens[cursor].end():tokens[end].start()]
            cursor = end + 1
        instances, separator = [], None
        while cursor < len(tokens) and IDENTIFIER.fullmatch(tokens[cursor].group()):
            name = tokens[cursor]
            cursor += 1
            arrays = []
            while cursor in closing and tokens[cursor].group() == '[':
                end = closing[cursor]
                arrays.append(text[tokens[cursor].start():tokens[end].end()])
                cursor = end + 1
            if cursor not in closing or tokens[cursor].group() != '(':
                break
            end = closing[cursor]
            instances.append({'name': name.group(), 'name_start': name.start(),
                              'arrays': arrays, 'separator': separator,
                              'ports': text[tokens[cursor].end():tokens[end].start()]})
            cursor = end + 1
            if cursor >= len(tokens):
                break
            if tokens[cursor].group() == ';':
                yield {'type': token.group(), 'type_start': token.start(),
                       'type_end': token.end(), 'params': params, 'instances': instances}
                idx = cursor
                break
            if tokens[cursor].group() != ',':
                break
            separator = tokens[cursor]
            cursor += 1
        idx += 1
