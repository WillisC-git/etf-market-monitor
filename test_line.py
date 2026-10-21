import json
import os
import sys
import urllib.error
import urllib.request

TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '').strip()
USER_ID = os.getenv('LINE_USER_ID', '').strip()

if not TOKEN or not USER_ID:
    sys.exit('Missing LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID GitHub Secret.')

payload = {
    'to': USER_ID,
    'messages': [{
        'type': 'text',
        'text': 'ETF Market Monitor V3.0\nLINE 推播測試成功！\nGitHub Actions 已成功連接 LINE Messaging API。',
    }],
}
req = urllib.request.Request(
    'https://api.line.me/v2/bot/message/push',
    data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
    headers={
        'Authorization': f'Bearer {TOKEN}',
        'Content-Type': 'application/json',
    },
    method='POST',
)
try:
    with urllib.request.urlopen(req, timeout=20) as response:
        print(f'LINE push API HTTP {response.status}')
        print('LINE accepted the test message request. Check your LINE chat for delivery.')
except urllib.error.HTTPError as error:
    print(f'LINE push API HTTP {error.code}')
    print('Check token, recipient user ID, and whether the user added the official account.')
    sys.exit(1)
except urllib.error.URLError:
    sys.exit('LINE API connection failed. Check network access and retry.')
