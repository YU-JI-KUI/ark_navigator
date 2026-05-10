import hmac
import base64
from urllib.parse import urlencode


def generate_app_sign(app_key, app_secret, open_api_request_time):
    if app_key is None:
        return None

    # 构造参数字典
    params = {
        "openApiRequestTime": str(open_api_request_time),
        "appKey": app_key,
        "appSecret": app_secret
    }

    # URL 编码并转为小写
    query_string = urlencode(params).lower()

    # 使用 HMAC-SHA1 签名
    hmac_obj = hmac.new(app_secret.encode('utf-8'), query_string.encode('utf-8'), 'sha1')

    # Base64 编码
    sign = base64.b64encode(hmac_obj.digest()).decode('utf-8')

    return sign
