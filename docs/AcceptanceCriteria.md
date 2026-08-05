# AcceptanceCriteria.md — AI Christmas Tree Decorator

อ้างอิงจาก [[Product.md]] และ [[Spec.md]] — ทุกข้อต้องเช็คได้จริง (pass/fail) ไม่ใช่ความเห็น
ใช้โดย: Builder (เช็คก่อนส่งงาน) และ Challenger (เช็คก่อน merge/deploy)

## AC-1: Input Handling
- [ ] อัปโหลด JPG/PNG สำเร็จ ทั้ง Input A (ต้นเปล่า) และ Input B (element)
- [ ] อัปโหลดไฟล์ผิดประเภท (เช่น .gif, .webp, .pdf) → ระบบ reject พร้อม error message ที่อ่านเข้าใจ (ไม่ crash)
- [ ] อัปโหลดไฟล์เกินขนาดที่กำหนด → reject พร้อม error message
- [ ] อัปโหลด Input B มากกว่า 1 ไฟล์ → ระบบปฏิเสธหรือรับแค่ไฟล์แรก (ต้องเลือกพฤติกรรมชัดเจน ไม่ใช่ undefined behavior)

## AC-2: Background Removal
- [ ] Input B ผ่าน rembg แล้วได้ PNG ที่มี alpha channel จริง (ตรวจสอบไฟล์ output ไม่ใช่แค่ไม่ error)
- [ ] User เห็น preview ผลลัพธ์การตัด background ก่อนกดยืนยันไปขั้นตอนถัดไป
- [ ] กรณีตัดขอบไม่สะอาด (เช่น ยังมีเงา/ขอบพื้นหลังหลงเหลือ) — user สามารถยกเลิก/อัปโหลดใหม่ได้ ไม่ใช่ต้องรันจนจบ pipeline

## AC-3: Image Generation
- [ ] เรียก gpt-image-2 สำเร็จด้วย input ที่ถูกต้อง (ต้นเปล่า + element โปร่งใส + prompt) → ได้ output image กลับมา
- [ ] Output resolution ตรงตามที่ user เลือก (default 4:5 หรือ ratio อื่นที่เลือก)
- [ ] แสดงผล 3 ภาพเรียงกันตามที่ Product.md ระบุ: ต้นเปล่า → element → ผลลัพธ์
- [ ] User ดาวน์โหลด output image ได้จริง (ไฟล์เปิดได้ ไม่เสียหาย)

## AC-4: Error Handling & Billing Integrity (สำคัญเพราะเรียก API ที่เสียเงินจริง)

*ปรับ 2026-08-05: ระบบ credit balance ถูกยกเลิก (Product.md ข้อ 6) เกณฑ์เดิมวัดจาก "ยอด credit ขยับกี่หน่วย" ซึ่งไม่มีแล้ว จึงเขียนใหม่ให้วัดสิ่งที่ credit เคยเป็นตัวแทน คือ **จำนวน billable API call** — เข้มเท่าเดิม ตรวจได้ตรงกว่าเดิม*

**คุณสมบัติหลัก**: 1 request ที่ผ่าน confirm แล้ว ทำให้เกิด billable API call ได้**ไม่เกิน 1 ครั้ง** และ request ที่ fail ต้อง**ไม่เกิดเลย**

- [ ] gpt-image-2 API timeout/fail → user เห็น error message ชัดเจน, row จบที่ `api_failed` และ **ไม่มี `usage` บันทึกไว้** (= ไม่มีค่าใช้จ่าย)
- [ ] rembg fail → user เห็น error, ไม่ไปต่อ pipeline โดยอัตโนมัติ, ไม่มีการเรียก image API เลย
- [ ] เงินในบัญชี OpenAI หมด → error บอกชัดว่าต้องไปเติมที่ไหน ไม่ใช่ error code ดิบ
- [ ] ยิง `POST /api/generate/{id}` ซ้ำกับ request เดิม (ทั้งแบบเรียงกันและแบบ race พร้อมกัน) → สำเร็จ 1 ครั้ง อีกครั้งได้ 409, image API ถูกเรียก**ครั้งเดียว**
- [ ] Confirm dialog แสดงทุกครั้งก่อน generate จริง — กด generate ไม่ trigger การเรียก API ทันทีจนกว่าจะ confirm (กัน double-click เสียเงินฟรี)
- [ ] ทุก exception หลัง `claim()` ต้องทำให้ row จบที่สถานะ terminal — row ค้าง `calling_api` ถาวร = retry ไม่ได้อีกเลย
- [ ] ไม่มีไฟล์ไหนในโปรเจกต์กลับมาเก็บ balance ท้องถิ่นอีก (OpenAI ไม่เปิด endpoint ให้อ่านยอดคงเหลือ ตัวเลขที่โชว์จะเป็นเลขที่ต้องกรอกมือและผิดได้ตลอด)

## AC-5: Quality Bar (เชื่อมกับ Success Metric ใน Product.md — ยังเป็นร่าง ต้องคุยตัวเลขจริงก่อน)
- [ ] สุ่มทดสอบ **30 รูป** — วัด % ที่ผลลัพธ์ "สมจริงพอขายได้" โดยไม่ retry
- [ ] **Pass threshold: ≥70% (21/30 รูปขึ้นไปต้องผ่าน)** — เกณฑ์เริ่มต้นสำหรับ MVP รอบแรก (ยังไม่เคย tune prompt) ปรับขึ้นได้ภายหลังเมื่อมี baseline จริง

## 6. Definition of Done (MVP)
งานถือว่า "เสร็จพร้อม demo/launch" เมื่อ:
1. AC-1 ถึง AC-4 ผ่านครบทุกข้อ
2. AC-5 ผ่านเกณฑ์ ≥70% จากการทดสอบ 30 รูปจริง
3. Spec.md ข้อ 5 (Open Items) ตอบครบแล้วก่อนเริ่ม Builder (ไม่ใช่ตอบระหว่างทาง)

---
*สถานะ: ครบแล้ว — พร้อมใช้เป็นเกณฑ์ตรวจรับจริง*
