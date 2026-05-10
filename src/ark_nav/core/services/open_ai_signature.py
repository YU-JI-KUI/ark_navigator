#签名获取方法
from Cryptodome.Hash import SHA256
from Crypto.PublicKey import RSA
from Crypto.Signature import PKCS1_v1_5
import hashlib
import binascii
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.backends import default_backend

def get_sign(rsa_private_key, request_time):

    '''
    一、openApiRequestTime为接口调用时的时间戳（18位毫秒）
    二、rsaPrivateKey为秘钥，获取方式如前所述，登录科技网关获取
    '''
    ######
    # 将十六进制字符串转换为二进制字符串
    binary_key = binascii.a2b_hex(rsa_private_key)
    #  创建RSA公钥对象
    pkcs8_private_key = RSA.import_key(binary_key)
    ######## 注意这里签名用的是requestTime，务必保证是同一个
    h = SHA256.new(request_time.encode('utf-8'))
    signer = PKCS1_v1_5.new(pkcs8_private_key)
    signature = signer.sign(h).hex().upper()
    # 是openApiSignature的值return signature
    return signature


def get_sign_with_der(rsa_private_key, request_time, encoding="hex"):
    """
    使用 DER 格式的 RSA 私钥（Hex）对时间戳签名
    :param rsa_private_key_hex: DER 格式私钥的十六进制字符串
    :param timestamp: 时间戳（毫秒级字符串）
    :param encoding: "hex"（大写十六进制）或 "base64"
    :return: 签名字符串
    """

    # Step 1: Hex → DER
    der_data = binascii.unhexlify(rsa_private_key.strip())

    # Step 2: 加载私钥
    private_key = serialization.load_der_private_key(
        der_data,
        password=None,
        backend=default_backend()
    )

    # Step 3: 签名
    message = request_time.encode('utf-8')
    signature_bytes = private_key.sign(
        message,
        padding.PKCS1v15(),
        algorithm=hashlib.sha256()
    )

    # Step 4: 按指定格式编码
    if encoding.lower() == "hex":
        return signature_bytes.hex().upper()
    elif encoding.lower() == "base64":
        import base64
        return base64.b64encode(signature_bytes).decode('utf-8')
    else:
        raise ValueError("encoding must be 'hex' or 'base64'")
