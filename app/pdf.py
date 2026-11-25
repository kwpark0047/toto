"""아주 작은 PDF 작성기 (표준 라이브러리만).

이미지(JPEG)만 얹는 PDF 를 만든다. 인쇄용 메뉴판처럼 '그림 한 장 + 종이 크기'면 충분한
경우를 위한 것으로, 글자는 이미지 안에 그려 넣는다(한글 폰트를 PDF 에 심지 않아도 되게).
"""
import struct

MM = 72 / 25.4  # 1mm = 2.8346pt


class PDF:
    def __init__(self):
        self.pages = []

    def add_page(self, width_mm, height_mm, images):
        """images: [{'data': jpeg bytes, 'pixel_w', 'pixel_h', 'x_mm', 'y_mm', 'w_mm', 'h_mm'}]"""
        self.pages.append({"w": width_mm, "h": height_mm, "images": images})

    def build(self):
        objs = []          # 1-based object bodies (bytes without "n 0 obj")

        def add(body):
            objs.append(body)
            return len(objs)

        catalog = add(b"")   # 자리만 잡고 나중에 채운다
        pages_obj = add(b"")
        font_pages = []

        for page in self.pages:
            img_refs = []
            for im in page["images"]:
                head = (f"<< /Type /XObject /Subtype /Image /Width {im['pixel_w']} "
                        f"/Height {im['pixel_h']} /ColorSpace /DeviceRGB /BitsPerComponent 8 "
                        f"/Filter /DCTDecode /Length {len(im['data'])} >>").encode()
                ref = add(head + b"\nstream\n" + im["data"] + b"\nendstream")
                img_refs.append(ref)

            ops = []
            for ref, im in zip(img_refs, page["images"]):
                name = f"Im{ref}"
                w = im["w_mm"] * MM
                h = im["h_mm"] * MM
                x = im["x_mm"] * MM
                y = (page["h"] - im["y_mm"] - im["h_mm"]) * MM   # PDF 는 아래에서 위로
                ops.append(f"q {w:.3f} 0 0 {h:.3f} {x:.3f} {y:.3f} cm /{name} Do Q")
            content = "\n".join(ops).encode()
            content_ref = add(f"<< /Length {len(content)} >>".encode() + b"\nstream\n" + content + b"\nendstream")

            res = " ".join(f"/Im{ref} {ref} 0 R" for ref in img_refs)
            page_ref = add(
                (f"<< /Type /Page /Parent {pages_obj} 0 R "
                 f"/MediaBox [0 0 {page['w'] * MM:.3f} {page['h'] * MM:.3f}] "
                 f"/Resources << /XObject << {res} >> >> /Contents {content_ref} 0 R >>").encode())
            font_pages.append(page_ref)

        kids = " ".join(f"{p} 0 R" for p in font_pages)
        objs[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
        objs[pages_obj - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(font_pages)} >>".encode()

        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]
        for i, body in enumerate(objs, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
        xref_at = len(out)
        out += f"xref\n0 {len(objs) + 1}\n".encode()
        out += b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode()
        out += (f"trailer\n<< /Size {len(objs) + 1} /Root {catalog} 0 R >>\n"
                f"startxref\n{xref_at}\n%%EOF\n").encode()
        return bytes(out)


PAPERS = {           # mm (세로)
    "A6": (105, 148),
    "A5": (148, 210),
    "A4": (210, 297),
    "B4": (250, 353),
    "A3": (297, 420),
}

# 한 장에 여러 개 넣을 때 쓸 수 있는 용지
MULTI_PAPERS = ("A4", "B4", "A3")
