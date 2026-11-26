# رسم حدود المباني مقابل النقاط | Building Outlines vs POI Nodes

## بالعربية (Arabic)

### 1. الأفضلية: رسم حدود المبنى (Building Outline)
- يفضل دائماً في خريطة الشارع المفتوحة رسم **مضلع مبنى المسجد الفعلي** بدلاً من الاكتفاء بوضع نقطة (Node).
- يعكس شكل المبنى مساحته الدقيقة واتجاه قبلته وموقعه الحقيقي على صور الأقمار الصناعية.

### 2. كيفية دمج نقطة المسجد في المبنى (Subsuming POI into Building)
- إذا وجدت مسجداً مرسوماً كنقطة (Node) داخل حدود مبنى (Way)، فهذا يعتبر تكراراً (`duplicate_poi`).
- **الحل الصحيح:**
  1. انقل جميع وسوم النقطة (`name`, `amenity=place_of_worship`, `religion=muslim`, `denomination=sunni`) إلى مضلع المبنى.
  2. تأكد من أن وسم المبنى هو `building=mosque` وليس `building=yes`.
  3. احذف النقطة المكررة.

### 3. متى نستخدم النقطة (Node)؟
- عندما يكون المصلى داخل مبنى متعدد الأغراض (مثل: مصلى داخل مطار، أو داخل مجمع تجاري/مول، أو داخل مستشفى أو محطة وقود).
- في هذه الحالة: ضع نقطة داخل المبنى بوسم `amenity=place_of_worship` و `religion=muslim` ولا تغير وسم مبنى المجمع نفسه.

---

## English (English)

### 1. Best Practice: Building Outlines
- Mapping the physical building polygon (`building=mosque`) is always preferred over standalone POI nodes.
- Outlines represent true footprint area, architecture, and prayer orientation towards Mecca (Qibla).

### 2. Merging Nodes into Outlines (Avoiding Duplicate POIs)
- If a POI node sits inside a building outline representing the same mosque, merge them:
  1. Transfer the node's tags (`name`, `name:ar`, `name:en`, `amenity=place_of_worship`, `denomination=sunni`) directly to the building polygon.
  2. Set `building=mosque` on the polygon.
  3. Delete the redundant inner node.

### 3. When are POI Nodes Appropriate?
- Indoor prayer rooms or musallas located inside large multi-purpose complexes (malls, airports, hospitals, highway rest stops).
