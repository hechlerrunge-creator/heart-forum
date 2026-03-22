import os
dirs = [
    'd:/AI测试/forum/templates/admin',
    'd:/AI测试/forum/templates/user',
    'd:/AI测试/forum/static/css',
    'd:/AI测试/forum/static/js',
]
for d in dirs:
    os.makedirs(d, exist_ok=True)
    print(f'Created: {d}')
print('All done.')
