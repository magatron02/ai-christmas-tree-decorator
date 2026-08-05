# Spec.md — AI Christmas Tree Decorator (Technical Spec)

อ้างอิงจาก [[Product.md]] — ไฟล์นี้แปล "ทำอะไร" เป็น "ทำยังไง" สำหรับ Builder ใช้เขียนโค้ด
Builder ห้ามแก้ค่าในไฟล์นี้เอง — ถ้าเจอปัญหา spec ไม่ครอบคลุม ให้ยกกลับ Architect

## 1. Stack (เสนอ — รอยืนยัน)
- **Backend**: Python (FastAPI) — เหตุผล: เรียก OpenAI SDK ตรง, จัดการ background-removal (rembg เป็น Python lib) ได้ในระบบเดียว
- **Background removal**: `rembg` (local, ไม่มี cost ต่อครั้ง) — fallback เป็น manual upload ที่ user ตัดมาเองแล้ว (Photoshop) ถ้า auto-remove คุณภาพไม่พอ
- **Image-gen**: OpenAI API — `gpt-image-2`
- **Frontend**: เว็บง่าย ๆ (internal tool ใช้คนเดียว) — **ใช้ Factory design system** (ดู [[factory-design-system.md]]) เป็น visual styling: dark theme, framework-free CSS, ไม่มี build step ผูกกับ font/component library — เหมาะกับงาน internal tool ที่ไม่ต้อง overhead ของ design framework เต็มรูปแบบ
- **Storage**: **Local disk** — เก็บ input/output image บนเครื่องที่รันระบบ (ตัดสินใจแล้ว: MVP ใช้คนเดียว ไม่ต้อง scale)
- **Auth**: **ไม่มี** — MVP ใช้คนเดียวบนเครื่องตัวเอง (ปรับ 2026-08-05) เดิมกำหนดให้มี single-account record ไว้เก็บ credit balance แต่ระบบ credit ถูกยกเลิกแล้ว (ดู Product.md ข้อ 6) จึงไม่เหลือสิ่งที่ account record ต้องเก็บ — ไม่มี login/signup, ไม่มีตาราง account
- **การคิดเงิน**: เงินอยู่ในบัญชี OpenAI ระบบไม่เก็บ balance ท้องถิ่น (OpenAI ไม่เปิด endpoint ให้อ่านยอดคงเหลือ) — บันทึก `usage` token จริงของทุกภาพลง state log แทน แล้วสรุปยอดที่ใช้ไปที่ `GET /api/usage`

## 2. Data Flow
```
[User] 
  → อัปโหลด Input A (ต้นเปล่า, JPG/PNG)
  → อัปโหลด Input B (element, JPG/PNG)
[System]
  → validate ไฟล์ (ดูข้อ 3)
  → Input B → rembg → element_transparent.png
  → build prompt (ดูข้อ 4)
  → สร้าง request_id, บันทึก state: pending
  → [User] ยืนยันผ่าน confirm dialog
  → state: calling_api
  → call gpt-image-2 API: [Input A, element_transparent.png, prompt] → output_image
  → API สำเร็จ → state: api_success → บันทึก usage (token ที่ใช้จริง) + log เต็ม (ดูข้อ 7)
  → API ล้มเหลว → state: api_failed → ไม่บันทึก usage (= ไม่มีค่าใช้จ่าย)
[User]
  → เห็นผลลัพธ์ 3 ภาพเรียง (ต้นเปล่า → element → ผลลัพธ์) → state: delivered
  → ดาวน์โหลด output_image
```
หมายเหตุ (ปรับ 2026-08-05): เดิมข้อนี้กำหนด "หัก credit หลัง api_success" — ระบบ credit ถูกยกเลิกแล้ว
สิ่งที่แทนที่คือ **บันทึก usage หลัง api_success เท่านั้น** row ที่มี `usage` = row ที่เสียเงิน
row ที่ไม่มี = ไม่เสีย ทำให้ "จุดที่เสียเงิน" กับ "จุดที่มีผลลัพธ์จริง" ยังเป็นจุดเดียวกันเหมือนเดิม

**คุณสมบัติที่ต้องคงไว้ (แทนที่กฎ "ห้ามหัก credit ก่อนสำเร็จ")**:
> 1 request ที่ผ่าน confirm แล้ว ทำให้เกิด billable API call ได้**ไม่เกิน 1 ครั้ง**
> และ request ที่ fail ต้อง**ไม่เกิดเลย**

## 3. Input Validation (ต้องกันไว้ตั้งแต่ Builder เขียน — กัน scope หลุดเป็น "error handling ทำทีหลัง")
- **รูปแบบไฟล์**: JPG, PNG เท่านั้น — reject อื่น ๆ พร้อม error message ชัดเจน
- **ขนาดไฟล์สูงสุด**: กำหนด (แนะนำ 10MB/ไฟล์ — ต้องเช็ค limit จริงของ gpt-image-2 API ตอน implement)
- **จำนวนไฟล์ต่อ request**: Input A = 1 ไฟล์, Input B = 1 ไฟล์ (ตาม Product.md decision: ทีละ element)
- **กรณี rembg ตัด background แล้วผลลัพธ์แย่** (เช่น element โปร่งใส/มันวาวเกินไป ตัดขอบไม่สะอาด): ต้องมี fallback ให้ user เห็น preview ก่อนส่งเข้า gpt-image-2 และแก้ไข/อัปโหลดใหม่ได้ — ไม่ auto-ส่งต่อทันทีโดยไม่ให้ user เห็น

## 4. Prompt Design (จุดเสี่ยงสูงสุดของโปรเจกต์ — ต้องมี baseline ทดสอบก่อนขยาย)
- Prompt ต้องระบุชัด: "นำ element จากภาพที่ 2 (โปร่งใส) ไปวางบนต้นไม้ภาพที่ 1 กระจายอย่างสมจริงตามธรรมชาติของการแขวนของตกแต่งจริง"
- ต้องคุม: ปริมาณ/ความหนาแน่น, ตำแหน่ง (กระจายทั่วต้น ไม่กระจุก), ขนาดสัดส่วนเทียบต้น, แสงเงาให้เข้ากับภาพต้นฉบับ
- **ต้องทำ prompt template แยกเป็นไฟล์ setting ไม่ hardcode ในโค้ด** — เพราะจะต้อง iterate บ่อยตอนทดสอบ (เกี่ยวกับ Success Metric ใน Product.md)

## 5. Open Items (ต้องตอบก่อน Builder เริ่มจริง — ไม่ใช่แค่ "เดี๋ยวค่อยว่ากัน")
- [x] Storage: **Local disk**
- [x] Auth: **ไม่มี** (ปรับ 2026-08-05) — เดิมกำหนด single-account ไว้เพื่อเก็บ credit balance อย่างเดียว พอยกเลิก credit ก็ไม่เหลืออะไรให้ account record เก็บ (ดูข้อ 1 Stack)
- [x] Rate limit: **ไม่ต้องมี — ใช้ confirm dialog แทน** ก่อนกด generate ทุกครั้ง (เพียงพอสำหรับ single-user, กัน double-click เสียเงินฟรีได้ตรงจุดกว่า rate limit ที่ออกแบบมาสำหรับ multi-user) — เสริมด้วย `claim()` ฝั่ง server ที่ทำให้ 1 request ยิง API ได้ครั้งเดียว
- [x] gpt-image-2 resolution/pixel constraint: **รองรับ custom resolution** — ต้องหารด้วย 16 ลงตัวทั้งกว้าง/สูง, aspect ratio ต้องอยู่ระหว่าง 1:3–3:1, ความละเอียดสูงสุด 3840x2160 (เกิน 2560x1440 ถือเป็น experimental) → 4:5 (default ที่ตัดสินใจไว้) กำหนดตรง ๆ ได้ เช่น 1536x1920 (หารด้วย 16 ลงตัว, ratio ตรง 4:5 พอดี)
- [x] **ความเสี่ยง `images.edit` reject gpt-image-2: ทดสอบแล้ว ไม่ reproduce** (2026-08-05) — รัน `scripts/check_edit_endpoint.py` เรียก endpoint จริง: `models.retrieve('gpt-image-2')` ผ่าน (owned_by=system) และ `images.edit(model='gpt-image-2', image=[2 ไฟล์], size='1536x1920')` คืนภาพ 1536×1920 สำเร็จ **ไม่ต้อง fallback ไป gpt-image-1.5** — bug ตามรายงานเดิมแก้แล้วหรือไม่เคยกระทบ config นี้
  (ระหว่างทางเจอ error คนละเรื่อง: `billing_hard_limit_reached` ซึ่งเป็นเพดานเงินฝั่งบัญชี ไม่ใช่ endpoint ปฏิเสธโมเดล — เติมเงินแล้วผ่าน)

## 6. Error Handling (ต้องมี — ไม่ใช่ nice-to-have)
- gpt-image-2 API fail/timeout → แสดง error ให้ user, **ห้ามบันทึก usage** ถ้า generation ไม่สำเร็จ (ปรับ 2026-08-05 จากเดิม "ห้ามหัก credit")
- **เงินในบัญชี OpenAI หมด** → API ตอบ `billing_hard_limit_reached` → แปลงเป็นข้อความบอก user ว่าต้องไปเติมที่ platform.openai.com (ไม่มี balance ท้องถิ่นให้เช็คล่วงหน้าได้)
- rembg fail (เช่นภาพซับซ้อนเกินตัดไม่ได้) → fallback ตามข้อ 3
- ผลลัพธ์ภาพออกมาแล้วดู "ไม่สมจริง" (คุณภาพต่ำ แต่ API ไม่ error) → นี่คือ product quality issue ไม่ใช่ system error — วัดด้วย Success Metric ใน Product.md ไม่ใช่ error handling ในเลเยอร์นี้

## 7. Reconciliation (กันเคส: API สำเร็จฝั่ง server แต่ user ไม่เห็นผล — เช่น network หลุดตอนส่งกลับ)
**ปัญหาที่ต้องกัน**: ถ้าคิดเงินตอนเริ่ม request แล้ว network หลุดก่อนส่งผลถึง user → user เสียเงิน แต่ไม่เคยเห็นภาพ ทั้งที่ระบบทำงานถูกต้องทุกจุด

**Design (สำหรับ scope MVP — local disk, single-user, ไม่ต้องมี queue/background worker เต็มรูปแบบ):**
1. **State log**: ทุก request มี `request_id` และสถานะ `pending → calling_api → api_success/api_failed → delivered` บันทึกลง SQLite หรือไฟล์ JSON เดียว (ไม่ต้องระบบซับซ้อน)
2. **จุดบันทึกค่าใช้จ่าย**: บันทึก `usage` หลัง `api_success` เท่านั้น (ดู Data Flow ข้อ 2) — ทำให้ "จุดเสียเงิน" กับ "จุดมีผลลัพธ์จริง" เป็นจุดเดียวกัน ลดความซับซ้อนเรื่อง edge case. `billed` เป็นค่า**คำนวณ**จากการมี `usage` ไม่ใช่ flag แยก จึงเพี้ยนจากความจริงไม่ได้
3. **หน้า "ประวัติการสร้างภาพ"**: query จาก state log — ถ้า network หลุดตอนส่งผลกลับ browser (แต่ OpenAI คิดเงินไปแล้วเพราะ API สำเร็จจริง) user เปิดหน้านี้แล้วเห็นผลลัพธ์ย้อนหลังได้ ไม่ต้องมี retry job อัตโนมัติสำหรับ MVP นี้
4. **Request ค้างสถานะ `calling_api` นานผิดปกติ** (เช่น ระบบ crash กลางทาง): ทำ manual check ผ่าน log ได้ในระดับ single-user — ไม่ต้อง auto-retry ใน MVP (เพิ่มทีหลังถ้าจำเป็นจริง)
   **ข้อจำกัดที่รับไว้ (2026-08-05)**: สถานะนี้เป็นจุดเดียวที่ log ตอบเรื่องเงินไม่ได้ — ไม่รู้ว่า call ถึง OpenAI ก่อนระบบตายหรือเปล่า ตอนมี credit balance ท้องถิ่นเคยรู้แน่ว่าไม่ถูกหัก ตอนนี้ต้องไปดูหน้า usage ของ OpenAI ตัดสิน (แลกมากับการไม่ต้องดูแลตัวเลขคู่ขนานที่เพี้ยนได้ตลอดเวลา)
5. **Request ค้างสถานะ `pending`** (user กด Generate แล้ว cancel ที่ confirm dialog): ไม่เคยถึง API จึงไม่มีค่าใช้จ่ายแน่นอน — เก็บกวาดด้วย `python -m backend.services.storage prune` (ลบเฉพาะ row ที่ `pending` และเก่าเกิน 24 ชม. พร้อมไฟล์ที่ไม่มีใครอ้างถึงแล้ว) สถานะอื่นเก็บถาวรทั้งหมดเพราะเป็นบันทึกการใช้เงิน

**เหตุผลที่ไม่ทำซับซ้อนกว่านี้ใน MVP**: scope ปัจจุบันคือ local disk + คนใช้คนเดียว ความเสี่ยงจาก edge case นี้เกิดไม่บ่อยและตรวจสอบเองได้ทันที ไม่คุ้มที่จะสร้าง background job/queue system ตั้งแต่ MVP รอบแรก — ถ้าขยายเป็น multi-user ใน V1.1 ต้อง revisit design นี้ใหม่

---
*สถานะ: Open Items ตอบครบแล้ว รวมความเสี่ยง edit endpoint ที่ทดสอบกับ API จริงแล้วว่าใช้งานได้ (2026-08-05)*
*อัปเดต 2026-08-05: ยกเลิกระบบ credit balance ทั้งหมด — ดู Product.md ข้อ 6 สำหรับเหตุผลและสิ่งที่แทนที่*
