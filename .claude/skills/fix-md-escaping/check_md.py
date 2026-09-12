#!/usr/bin/env python3
"""Поиск и починка символов, ломающих рендеринг Markdown.

Работает только с текстом вне кода: содержимое ``` -блоков, inline-кода
в бэктиках, адресов ссылок ](...) и автоссылок <http...> не трогается никогда.

  check_md.py FILE|DIR ...            отчёт, код возврата 1 при находках
  check_md.py --fix FILE|DIR ...      починить автоисправимое, отчёт по остальному
  check_md.py --fix --only $ FILE     починить только один класс
  check_md.py --strict FILE           плюс требовать язык у блоков кода
"""
import argparse
import os
import re
import sys

# --- разбор строки на код и не-код -----------------------------------------

CODE_SPAN = re.compile(r'(?<!\\)(`+)(?:.|\n)*?(?<!`)\1(?!`)')
LINK_DEST = re.compile(r'\]\([^)\s]*(?:\s+"[^"]*")?\)')
AUTOLINK = re.compile(r'<[a-zA-Z][a-zA-Z0-9+.-]*:[^<>\s]*>|<[^<>\s@]+@[^<>\s]+>')


def split_line(line):
    """-> [(text, is_code), ...]. is_code=True — кусок, который нельзя менять."""
    spans = []
    for rx in (CODE_SPAN, LINK_DEST, AUTOLINK):
        spans.extend((m.start(), m.end()) for m in rx.finditer(line))
    spans.sort()
    merged = []
    for s, e in spans:
        if merged and s < merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    out, pos = [], 0
    for s, e in merged:
        if s > pos:
            out.append((line[pos:s], False))
        out.append((line[s:e], True))
        pos = e
    if pos < len(line):
        out.append((line[pos:], False))
    return out


def plain(line):
    return ''.join(t for t, code in split_line(line) if not code)


def edit_plain(line, fn):
    return ''.join(t if code else fn(t) for t, code in split_line(line))


# --- правила ----------------------------------------------------------------
# fix=None — только отчёт: автоматическая замена требует решения человека.

def fix_dollar(t):
    return re.sub(r'(?<!\\)\$', r'\\$', t)


def fix_angle(t):
    return re.sub(r'(?<!\\)<(?=[a-zA-Z/!?])', r'\\<', t)


RULES = [
    ('$', 'пара $…$ на строке съедается как inline-математика',
     lambda t: len(re.findall(r'(?<!\\)\$', t)) >= 2, fix_dollar),
    ('<', 'сырой <tag> проглатывается как HTML',
     lambda t: re.search(r'(?<!\\)<[a-zA-Z/!?]', t), fix_angle),
    ('~~', 'двойная тильда включает зачёркивание', lambda t: '~~' in t, None),
    ('[]', 'скобки станут ссылкой: в файле есть определение [label]:',
     None, None),   # особое правило: нужны определения ссылок из всего файла
    ('1.', 'год или число в начале строки превратится в нумерованный список',
     None, None),   # особое правило: нужен контекст соседних строк, см. scan()
]
RULE_FIX = {k: f for k, _, _, f in RULES}


NUMBERED = re.compile(r'^\s*(\d+)\.\s')


def lone_numbered(lines, idx):
    """«2026. Текст» в прозе: число 2+ знаков и рядом нет настоящего списка."""
    m = NUMBERED.match(lines[idx])
    if not m or len(m.group(1)) < 2:
        return False
    for j in (idx - 1, idx + 1):          # сосед по списку делает строку списком
        if 0 <= j < len(lines) and NUMBERED.match(lines[j]):
            return False
    for j in range(idx - 1, max(-1, idx - 4), -1):   # пустая строка, выше — список
        if lines[j].strip() and NUMBERED.match(lines[j]):
            return False
    return True


BQ = re.compile(r'^\s{0,3}(?:>\s?)+')


def unquote(line):
    """Снять префикс цитаты: блок кода внутри > остаётся блоком кода."""
    return BQ.sub('', line)


LINK_DEF = re.compile(r'^\s{0,3}\[([^\]]+)\]:\s')
SHORTCUT = re.compile(r'(?<!\\)\[([^\]]+)\](?![(\[:])')


def shortcut_becomes_link(text, labels):
    """[текст] рендерится буквально, пока нет определения [текст]: url."""
    return any(m.group(1).strip().lower() in labels for m in SHORTCUT.finditer(text))


def scan(path, do_fix, only, strict=False):
    lines = open(path, encoding='utf-8').read().split('\n')
    labels = {m.group(1).strip().lower() for m in map(LINK_DEF.match, lines) if m}
    fence = None
    found = []          # (lineno, key, desc, text)
    fences = []         # (lineno, info)
    out = []
    for i, line in enumerate(lines, 1):
        m = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', unquote(line))
        if m and (fence is None or m.group(1)[0] == fence[0]):
            if fence is None:
                fence = m.group(1)
                fences.append((i, m.group(2).strip()))
            elif len(m.group(1)) >= len(fence):
                fence = None
            out.append(line)
            continue
        if fence is not None:
            out.append(line)
            continue

        p = plain(line)
        new = line
        for key, desc, hit, fixer in RULES:
            if hit is None:
                if key == '1.' and not lone_numbered(lines, i - 1):
                    continue
                if key == '[]' and not shortcut_becomes_link(p, labels):
                    continue
            elif not hit(p):
                continue
            if do_fix and fixer and (only is None or key in only):
                new = edit_plain(new, fixer)
            else:
                found.append((i, key, desc, line.strip()))
        out.append(new)

    # структура: чинить нельзя, только сказать
    if fence is not None:
        found.append((0, 'fence', 'незакрытый блок кода ```', ''))
    if strict:
        for ln, info in fences:
            if not info:
                found.append((ln, 'lang', 'блок кода без указания языка', ''))
    for ln, width, kind in ragged_tables(lines):
        found.append((ln, 'table', kind, ''))

    changed = False
    if do_fix:
        new_text = '\n'.join(out)
        if new_text != '\n'.join(lines):
            open(path, 'w', encoding='utf-8').write(new_text)
            changed = True
    return found, changed


def ragged_tables(lines):
    block, start, fence = [], None, False
    problems = []
    for i, line in enumerate(lines + [''], 1):
        line = unquote(line)
        if re.match(r'^\s{0,3}(```|~~~)', line):
            fence = not fence
        if not fence and line.startswith('|'):
            if start is None:
                start = i
            block.append(line)
            continue
        if start is not None:
            # \| — экранированная труба внутри ячейки, колонку не делит
            widths = {r.replace('\\|', '').count('|') for r in block}
            if len(widths) > 1:
                problems.append((start, widths, 'в таблице строки разной ширины: %s' % sorted(widths)))
            block, start = [], None
    return problems


def targets(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if f.endswith('.md'):
                        yield os.path.join(root, f)
        else:
            yield p


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('paths', nargs='+')
    ap.add_argument('--fix', action='store_true', help='применить автоисправления')
    ap.add_argument('--only', action='append', help='чинить только этот класс ($, <, *)')
    ap.add_argument('--strict', action='store_true',
                    help='дополнительно требовать язык у каждого блока кода; '
                         'в блоках с текстом промптов и ASCII-диаграммами языка нет по делу, '
                         'поэтому по умолчанию проверка выключена')
    a = ap.parse_args()

    total, fixed = 0, 0
    for path in targets(a.paths):
        found, changed = scan(path, a.fix, a.only, a.strict)
        if changed:
            fixed += 1
            print('ПОЧИНЕНО %s' % path)
        for ln, key, desc, text in found:
            total += 1
            print('%s:%d  [%s] %s' % (path, ln, key, desc))
            if text:
                print('        %s' % text[:150])
    if a.fix:
        print('\nфайлов изменено: %d; осталось на ручное решение: %d' % (fixed, total))
    else:
        print('\nнаходок: %d' % total)
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main())
