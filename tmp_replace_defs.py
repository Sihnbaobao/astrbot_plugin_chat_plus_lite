# -*- coding: utf-8 -*-
p = 'pages/control/app.js'
with open(p, encoding='utf-8') as f:
    lines = f.read().split('\n')
# 删除 6-82 行（0-based 5-81）
start = 5  # '/* ================= 字段定义 ================= */'
end = 81   # '];'  (0-based, CARDS 结束)
assert '字段定义' in lines[start], lines[start][:40]
assert lines[end].strip() == '];', lines[end]
new_defs = open('tmp_newdefs.txt', encoding='utf-8').read().split('\n')
lines = lines[:start] + new_defs + lines[end + 1:]
with open(p, 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('definitions replaced')
# 快速校验
src = '\n'.join(lines)
print('FIELDS 残留:', src.count('const FIELDS'))
print('EXTRA_META 存在:', 'const EXTRA_META' in src)
print('MASTERS 存在:', 'const MASTERS' in src)
print('buildMeta 存在:', 'function buildMeta' in src)