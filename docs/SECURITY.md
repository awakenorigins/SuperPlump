# SECURITY — SuperPlump

## Phòng thủ nhiều lớp
- **Xác thực:** JWT (HS256/RS256-JWKS) + phiên thu hồi được (jti) + refresh rotation. Token 13 ký tự & password chỉ lưu hash (sha256 / scrypt+salt). 2FA TOTP cho owner.
- **Chống dò:** lockout 5 lần/15' theo tài khoản, 50/15' theo IP; regnick 30/phút/IP; rate-limit nạp tiền.
- **Đầu vào:** zod validate mọi body → 400; helmet headers; giới hạn body 200kb.
- **Webhook:** HMAC-SHA256 raw-body + idempotent theo ref — replay không nhân đôi tiền.
- **Khóa mandate:** Ed25519, private key mã hóa **AES-256-GCM envelope** (MASTER_KEY→KMS), bản rõ không lưu.
- **RLS:** ví/sổ chỉ chủ thấy; vị trí thật chỉ 2 bên deal.
- **Preflight:** production từ chối boot nếu secret dev/khóa yếu/thiếu TLS.

## Bí mật
Đọc từ `*_FILE` (Docker/K8s secrets) ưu tiên hơn env. Không bao giờ log giá trị secret. `.env.production` chmod 600, không commit. Xoay khóa: đổi biến → restart (owner tự re-hash).

## Quy trình lỗ hổng
Báo: security@superplump.vn. Sự cố dữ liệu: tạo incident (deadline cơ quan 72h tự sinh), theo PRIVACY_PACK mục 5.

## Còn phải làm trước public
Cloud KMS thật · pen-test độc lập · WAF/rate-limit ở tầng proxy · secret scanning trong CI.
