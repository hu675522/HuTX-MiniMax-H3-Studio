"""Official OSS SDK in the isolated runtime; no secrets on argv/stdout/errors."""
import base64
import json
import logging
import sys


def main():
    logging.disable(logging.CRITICAL)
    request=json.load(sys.stdin)
    import oss2
    from oss2.credentials import StaticCredentialsProvider
    provider=StaticCredentialsProvider(request['access_id'],request['access_secret'],request.get('token'))
    bucket=oss2.Bucket(oss2.ProviderAuthV4(provider),'https://oss-cn-beijing.aliyuncs.com',
                      request['bucket'],region='cn-beijing',connect_timeout=20)
    key=request['key'];action=request['action']
    if action=='put':
        bucket.put_object(key,base64.b64decode(request['data']),headers={'Content-Type':'audio/wav','x-oss-object-acl':'private'})
    elif action=='delete':bucket.delete_object(key)
    elif action=='sign':
        print(json.dumps({'ok':True,'url':bucket.sign_url('GET',key,600,slash_safe=True)}));return
    else:raise ValueError()
    print('{"ok":true}')


if __name__=='__main__':
    try:main()
    except Exception:
        print('{"ok":false}');sys.exit(1)
