#!/usr/bin/env bash
# Sinh trọn bộ secrets production → .env.production (chmod 600). KHÔNG commit file này.
set -e
rand_hex(){ openssl rand -hex "$1"; }
rand_token(){ node -e "const c=require('crypto');const A='ABCDEFGHJKMNPQRSTUVWXYZ23456789';let o='';const b=c.randomBytes(26);for(let i=0;i<26;i++)o+=A[b[i]%A.length];console.log(o)"; }
OUT="${1:-.env.production}"
cat > "$OUT" << ENV
NODE_ENV=production
ALLOW_DEV_UUID=0
PGPASSWORD=$(rand_hex 24)
ADMIN_KEY=$(rand_hex 32)
OWNER_TOKEN=$(rand_token)   # owner = 26 ký tự (user thường vẫn 13 theo spec regnick)
SUPABASE_JWT_SECRET=$(rand_hex 48)
MASTER_KEY=$(rand_hex 32)
PAYMENT_WEBHOOK_SECRET=$(rand_hex 32)
EKYC_WEBHOOK_SECRET=$(rand_hex 32)
JWKS_URL=
ANTHROPIC_API_KEY=
ENV
chmod 600 "$OUT"
echo "✓ Đã sinh $OUT — OWNER_TOKEN nằm trong file, đọc MỘT lần, cất ví mật khẩu, đừng gửi qua chat."
