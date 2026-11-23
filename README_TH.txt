APEX AI TRADING — TELEGRAM ALERT WORKER (BETA)
================================================
รุ่นนี้ต่อยอดจาก PWA Starter เดิม โดยเพิ่ม Cloud Worker ที่ส่งข้อความและภาพกราฟเข้า Telegram
ระบบเป็น Analysis/Paper เท่านั้น ไม่เชื่อมบัญชีโบรกเกอร์และไม่ส่งคำสั่งซื้อขายจริง

สิ่งที่ทำได้
- BTCUSDT: ดึงแท่งเทียน 5 นาทีจาก Binance Spot API สาธารณะ
- XAU/USD: ดึงแท่งเทียน 5 นาทีจาก Twelve Data (ต้องมี API key)
- วิเคราะห์ EMA 9/21, RSI(14), ATR และเงื่อนไขแท่งเทียนแบบ rule-based
- สร้างภาพกราฟ Candlestick พร้อม EMA, ลูกศร BUY/SELL, Entry, SL, TP1-TP3 และเส้น scenario
- ส่งภาพและรายงานเข้า Telegram เมื่อพบสัญญาณใหม่
- คำสั่ง Telegram: /start /scan /status /help
- ตรวจตลาดเป็นรอบทุก 60 วินาที (ปรับได้) เมื่อ Cloud Worker ทำงาน

ข้อจำกัดสำคัญ
1. นี่คือระบบวิเคราะห์กฎเชิงเทคนิคเบื้องต้น ไม่ใช่โมเดล AI ที่ผ่านการฝึก/พิสูจน์ความแม่นยำ และไม่รับประกันกำไร
2. คะแนน Setup Score ไม่ใช่เปอร์เซ็นต์โอกาสชนะ
3. BTCUSDT จาก Binance ไม่เท่ากับ BTCUSD ของทุกโบรกเกอร์ ส่วน XAU/USD จาก Twelve Data อาจต่างจากราคา Bid/Ask ของโบรกเกอร์
4. ตัวเลข Entry/SL/TP เป็นระดับอ้างอิงจาก ATR ไม่ใช่คำสั่งซื้อขาย และยังไม่รวม spread, commission, slippage, swap หรือ contract specifications
5. ทุน $10 และ risk 0.25% เท่ากับ $0.025 ต่อครั้ง แต่ยังคำนวณ lot จริงไม่ได้หากไม่มีสเปกสัญญาของโบรกเกอร์ จึงห้ามถือว่าขนาดความเสี่ยงนี้ทำได้จริง
6. Worker ทำงาน 24/7 ได้เมื่อ deploy บนบริการ Cloud ที่เปิดใช้งานและมีค่าใช้จ่าย/โควตาตามผู้ให้บริการ ไม่ได้ทำงานจากโทรศัพท์โดยตรง
7. BTC ตลาดเปิด 24/7 แต่ XAU/USD มีช่วงตลาดปิด และ API อาจล่าช้าหรือขัดข้อง
8. ไม่ควรส่ง token หรือ API key ให้ผู้อื่นหรือใส่ไว้ในไฟล์ที่เผยแพร่สาธารณะ

การตั้งค่าผ่าน Android (ไม่ต้องใช้คอมพิวเตอร์)
A) สร้าง Telegram Bot
1. เปิด Telegram แล้วค้นหา @BotFather (ตรวจสอบบัญชีทางการ)
2. ส่ง /newbot แล้วทำตามขั้นตอน ตั้งชื่อและ username ให้บอต
3. BotFather จะให้ BOT TOKEN — เก็บเป็นความลับ ห้ามส่งในแชตนี้
4. เปิดแชตบอตที่สร้าง แล้วกด Start หลังจาก Worker เปิดใช้งาน

B) เตรียม API ราคาทอง
1. สมัครผู้ให้บริการ Twelve Data และสร้าง API key ตามแพ็กเกจ/ข้อจำกัดที่แสดงในบัญชี
2. ใช้ key ใน Environment Variable ชื่อ TWELVEDATA_API_KEY
3. BTC ใช้ Binance public endpoint ไม่ต้องใช้ API key สำหรับข้อมูลสาธารณะ

C) Deploy Worker บน Render
1. ต้องนำโฟลเดอร์โปรเจกต์นี้ขึ้น GitHub repository ส่วนตัว (สามารถทำผ่าน Chrome บน Android)
2. สร้างบัญชี Render และเชื่อม GitHub
3. เลือก New > Blueprint แล้วเลือก repository ที่มี render.yaml
4. ตั้งค่า TELEGRAM_BOT_TOKEN และ TWELVEDATA_API_KEY ใน Environment ของบริการ ห้ามใส่ในโค้ด
5. Deploy worker และดู Logs ว่าเริ่มทำงานได้
6. เปิด Telegram คุยกับบอตแล้วกด Start หรือส่ง /start
7. ส่ง /status และ /scan เพื่อทดสอบ

ทดสอบในเครื่อง (สำหรับผู้พัฒนา)
- Python 3.11+
- pip install -r requirements.txt
- คัดลอก .env.example เป็น .env แล้วตั้ง environment variables ใน shell/host
- python bot.py

ไฟล์ state/chats.json และ state/sent.json เก็บ chat IDs และป้องกันการแจ้งสัญญาณซ้ำ ควรเก็บ persistent disk หรือย้าย state ไปฐานข้อมูลก่อนใช้งานระยะยาว

ก่อนเงินจริง
- ต้องทำ backtest, out-of-sample และ forward/paper testing
- ต้องตรวจสอบ feed freshness, spread, slippage, fees และ broker contract specs
- เพิ่ม multi-timeframe, news calendar, BTC open interest/funding/liquidation และ alert monitoring ในเฟสถัดไป
- ห้ามเปิด auto-trading จากระบบรุ่นนี้
