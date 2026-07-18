import requests
import re

url = 'https://mp.weixin.qq.com/s/48H0Ad_SKj7HKNjKwb68og'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
    'Accept-Language': 'zh-CN,zh;q=0.9'
}
resp = requests.get(url, headers=headers, timeout=20)
print('status:', resp.status_code)
print('final url:', resp.url)
text = resp.text
patterns = [
    r'__biz=([\\w%\\-]+)',
    r'__biz\\"\\s*:\\s*\\"([\\w%\\-]+)\\"',
    r'profile_ext\\?action=home&__biz=([\\w%\\-]+)',
    r'__biz\\u003d([\\w%\\-]+)'
]
for p in patterns:
    m = re.search(p, text)
    print(p, '=>', m.group(1) if m else None)
idx = text.find('__biz')
print('idx', idx)
if idx != -1:
    start = max(0, idx-200)
    end = min(len(text), idx+200)
    snippet = text[start:end]
    print(snippet)
with open('data/raw/article_html_48H0Ad.html', 'w', encoding='utf-8') as f:
    f.write(text)
print('wrote data/raw/article_html_48H0Ad.html')
