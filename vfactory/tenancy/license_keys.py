"""授权文件的验签公钥（Ed25519，原始 32 字节的 base64）。键是 key_id（公钥 SHA-256 的前 16 位十六进制）。

只放公钥。私钥由蜂元保管（不进仓库、不进安装包），用 tools/license_sign.py keygen 生成，sign 签发授权文件。
生成正式密钥对以后，把 keygen 打印的那一行粘到下面（可以同时留旧公钥，换密钥期间旧授权照样认）。
"""
TRUSTED: dict = {
    # 'key_id': 'base64 公钥',
}
