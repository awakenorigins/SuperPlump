# BEAT 4 · Slot twin + phí duy trì — van chống lạm phát #3

## Cơ chế
| | Lv1 | Lv2 | Lv3 | Lv4 | Lv5 |
|--|--|--|--|--|--|
| Số slot twin | 1 | 1 | 2 | 3 | 5 |
| Phí mở twin thứ n (Nara) | — | — | 50k (thứ 3) | 150k (thứ 4) | 400k (thứ 5) |
| Phí duy trì/tháng | 0 | 0 | 20k | 50k | 120k |

## Vì sao
- Slot theo cấp: buộc chủ cày giỏi mới được nhiều twin (gắn với lao động thật).
- Phí mở & duy trì tăng dần: chi phí biên cao → phanh tự nhiên chống "quân đoàn twin" cày lạm phát.
- Twin không đóng phí → treo → không kiếm tiền được. Van xả rõ ràng.
- Doanh thu: bán slot bằng Nara (nguồn thu tinh tế, không phá 2 bất biến).

## API
GET /v1/me/twin-slots · POST /v1/twins/:id/maintenance/pay · POST /v1/twins (nay kiểm slot + thu phí).
