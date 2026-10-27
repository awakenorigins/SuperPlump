# HỒ SƠ ĐÁNH GIÁ TÁC ĐỘNG XỬ LÝ DỮ LIỆU CÁ NHÂN (khung theo NĐ 356/2025)
1. **Bên kiểm soát & DPO:** Công ty ___ · DPO: ___ (privacy@superplump.vn)
2. **Mô tả xử lý:** chợ thời gian — danh tính (eKYC mã tham chiếu), vị trí tin đăng (mờ ~300m công khai), giao dịch escrow, nội dung, bản thể số AI (nhãn bắt buộc, mandate ký số).
3. **Cơ sở & mục đích:** hợp đồng dịch vụ · đồng ý granular từng mục (location/marketing/twin_training/analytics/cross_border) — rút được trong app.
4. **Dữ liệu nhạy cảm & biện pháp:** vị trí → fuzz mặc định + RLS + chỉ 2 bên deal thấy thật · khóa mật mã → envelope KMS · sổ tài chính append-only · sự cố báo 72h (bảng incidents, deadline tự sinh).
5. **Chia sẻ/bên thứ ba:** đối tác eKYC ___, trung gian thanh toán (giấy phép NHNN số ___), hạ tầng cloud ___ (vị trí lưu trữ: VN).
6. **Chuyển xuyên biên giới:** ☐ Không ☐ Có (kèm hồ sơ ĐGTĐCDL + consent cross_border).
7. **Lưu giữ & xóa:** PII scrub theo yêu cầu (quyền được lãng quên); ledger giữ theo nghĩa vụ kế toán ___ năm.
8. **Rủi ro & giảm thiểu:** lộ vị trí (đã fuzz) · gian lận (fraud_flags, lockout, velocity) · rò khóa (KMS, secrets file) · mất dữ liệu (backup drill định kỳ).
9. **Phê duyệt:** ___ ngày ___
