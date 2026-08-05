# TestPlan.md — AI Christmas Tree Decorator

ใช้โดย: Challenger role — ตรวจก่อน merge/deploy ทุกครั้งที่มีผลต่อเงิน (ตามกติกา pipeline)
โปรเจกต์นี้มีผลต่อเงินโดยตรง เพราะโมเดลรายได้คือ pay-per-generation (Product.md section 6)

## 1. Billing Integrity Tests (ความสำคัญสูงสุด — ทดสอบก่อนสิ่งอื่นทั้งหมด)

*ปรับ 2026-08-05: ระบบ credit balance ถูกยกเลิก (Product.md ข้อ 6) เกณฑ์เดิมวัดจากยอด credit ที่ขยับ ตอนนี้วัดจาก **จำนวนครั้งที่ image API ถูกเรียก** (ทุกครั้ง = เงินจริง) และ **การมี `usage` ใน log** (row ที่มี = เสียเงิน, ไม่มี = ไม่เสีย)*

| Test Case | Expected Result |
|---|---|
| Generation สำเร็จปกติ | image API ถูกเรียก 1 ครั้ง, row มี `usage`, `billed=true` |
| gpt-image-2 API timeout | row จบที่ `api_failed`, ไม่มี `usage`, totals ไม่ขยับ |
| gpt-image-2 API return error (เช่น content policy reject) | เหมือนข้างบน |
| เงินในบัญชี OpenAI หมด (`billing_hard_limit_reached`) | error บอกว่าต้องไปเติมที่ไหน, ไม่มี `usage`, retry ได้ |
| Exception ที่ไม่คาดคิดหลัง claim (เช่น API key หาย) | row **ต้อง**จบที่ `api_failed` ไม่ค้าง `calling_api` (ค้าง = retry ไม่ได้ตลอดไป) |
| rembg fail ก่อนถึงขั้น gpt-image-2 | image API ไม่ถูกเรียกเลย, ไม่มี row เกิดขึ้น |
| User กด generate ซ้ำเร็ว ๆ (double-click) | Confirm dialog ผูกกับ request_id เดียว → คลิกที่สองได้ 409, image API ถูกเรียกครั้งเดียว |
| ยิง generate ซ้ำแบบ race (2 thread พร้อมกัน) | 1 ได้ 200 อีก 1 ได้ 409, image API ถูกเรียกครั้งเดียว |
| Replay URL ของ request ที่ delivered แล้ว | 409, ไม่เกิดภาพที่สอง |
| Network หลุดระหว่างรอผลลัพธ์ (แต่ generation สำเร็จฝั่ง server) | ต้องมี reconciliation — ภาพยังดาวน์โหลดได้จากหน้าประวัติ, `usage` บันทึกไว้ครบ |
| ขั้นตอนฟรีทั้งหมด (remove-bg, prepare) | image API ไม่ถูกเรียก, totals ไม่ขยับ |
| Grep ทั้ง repo | ไม่มีไฟล์ไหนเก็บ balance ท้องถิ่นหรือเรียก `/api/balance` |

## 2. Quality/Output Tests
| Test Case | Expected Result |
|---|---|
| Input A + Input B ปกติ (ต้นชัด, element ชัด) | ได้ output ที่ element ปรากฏบนต้นในตำแหน่งสมเหตุผล |
| Input B เป็นวัตถุมันวาว/โปร่งแสง (เช่นลูกบอลแก้ว) | ตรวจสอบว่าขอบตัด background ไม่เพี้ยน (จุดเสี่ยงที่คุยกันไว้ตอน background handling) |
| Input A เป็นต้นที่มีพื้นหลังซับซ้อน (คนเดินผ่าน, ของอื่นในเฟรม แบบ Image 1/3 ตัวอย่าง) | ผลลัพธ์ไม่หลอนเอาพื้นหลังมาปนกับต้น |
| Output resolution ตรงตาม ratio ที่เลือก | ตรวจสอบ pixel dimension ของไฟล์จริง |

## 3. Regression Tests (รันทุกครั้งก่อน deploy)
- [ ] AC-1 ถึง AC-4 ทั้งหมดใน AcceptanceCriteria.md
- [ ] Prompt template เปลี่ยนแล้วผลลัพธ์เก่ายังผ่านเกณฑ์เดิม (กัน prompt tuning ทำให้ quality เดิมพัง)

## 4. Sample Size สำหรับ Quality Bar (เชื่อมกับ AC-5)
- **N = 30 รูป**, pass threshold ≥70% (21/30 ขึ้นไป) — ตามที่ตกลงใน AcceptanceCriteria.md AC-5

## 5. Open Items
- [x] จำนวน N รูปทดสอบสำหรับ Quality Bar (AC-5): **30 รูป** — ดูข้อ 4
- [x] Reconciliation process: ออกแบบแล้วใน [[Spec.md]] ข้อ 7 — state log + บันทึก usage หลัง api_success + หน้าประวัติดึงผลย้อนหลัง (ไม่ต้อง auto-retry ใน MVP)
- [x] ต้นทุนต่อภาพ (2026-08-05): วัดจริง 1536×1920 = input 2674 token คงที่, output 565–1030 token **แกว่งทุกรอบแม้ input เหมือนกันเป๊ะ** → ทำนายราคาต่อภาพล่วงหน้าไม่ได้ ต้องเฉลี่ยจากของจริง. AC-5 (30 รูป) จะให้ 30 จุดข้อมูลโดยไม่ต้องรันเพิ่ม เพราะระบบบันทึก `usage` ทุกภาพอยู่แล้ว

---
*สถานะ: ครบแล้ว — พร้อมใช้เป็นแผนทดสอบจริง*
