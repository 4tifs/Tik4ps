import sys, os, struct, json, base64
from http.server import BaseHTTPRequestHandler

def make_custom_udta(comment_str='Patched by tik4ps.vercel.app', domain_str='tik4ps.vercel.app'):
    too_data = b'\x00\x00\x00\x01\x00\x00\x00\x00' + b'Lavf59.27.100'
    too_box = struct.pack('>I4s', 8 + len(too_data), b'data') + too_data
    too_item = struct.pack('>I4s', 8 + len(too_box), b'\xa9too') + too_box

    cmt_bytes = comment_str.encode('utf-8')
    cmt_data = b'\x00\x00\x00\x01\x00\x00\x00\x00' + cmt_bytes
    cmt_box = struct.pack('>I4s', 8 + len(cmt_data), b'data') + cmt_data
    cmt_item = struct.pack('>I4s', 8 + len(cmt_box), b'\xa9cmt') + cmt_box

    ilst1_payload = too_item + cmt_item
    ilst1_box = struct.pack('>I4s', 8 + len(ilst1_payload), b'ilst') + ilst1_payload

    hdlr1_payload = b'\x00\x00\x00\x00\x00\x00\x00\x00mdirappl\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    hdlr1_box = struct.pack('>I4s', 8 + len(hdlr1_payload), b'hdlr') + hdlr1_payload

    meta1_payload = b'\x00\x00\x00\x00' + hdlr1_box + ilst1_box
    meta1_box = struct.pack('>I4s', 8 + len(meta1_payload), b'meta') + meta1_payload

    dom_bytes = domain_str.encode('utf-8')
    pascal_name = bytes([len(dom_bytes)]) + dom_bytes
    hdlr2_payload = b'\x00\x00\x00\x00\x00\x00\x00\x00mdir\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' + pascal_name
    hdlr2_box = struct.pack('>I4s', 8 + len(hdlr2_payload), b'hdlr') + hdlr2_payload

    ilst2_payload = cmt_item
    ilst2_box = struct.pack('>I4s', 8 + len(ilst2_payload), b'ilst') + ilst2_payload

    meta2_payload = b'\x00\x00\x00\x00' + hdlr2_box + ilst2_box
    meta2_box = struct.pack('>I4s', 8 + len(meta2_payload), b'meta') + meta2_payload

    udta_payload = meta1_box + meta2_box
    return struct.pack('>I4s', 8 + len(udta_payload), b'udta') + udta_payload

SITE_UDTA = make_custom_udta('Patched by tik4ps.vercel.app', 'tik4ps.vercel.app')

def boxes(d, a, b):
    out = []; i = a
    while i + 8 <= b:
        n = int.from_bytes(d[i:i+4], 'big'); t = d[i+4:i+8]; h = 8
        if n == 1:
            n = int.from_bytes(d[i+8:i+16], 'big'); h = 16
        elif n == 0:
            n = b - i
        if n < h or i + n > b: raise ValueError(f'bad MP4 box {t!r} at {i}')
        out.append((t, i, n, h, d[i:i+n])); i += n
    if i != b: raise ValueError('box alignment')
    return out

def child(b, t, idx=0):
    a = [x[4] for x in boxes(b, 8, len(b)) if x[0] == t]
    if idx >= len(a): raise KeyError(t)
    return a[idx]

def box(t, p): return struct.pack('>I4s', 8 + len(p), t) + p

def rebuild(b, repl=None, remove=(), append=()):
    repl = repl or {}; seen = {}; out = []
    for t, i, n, h, x in boxes(b, 8, len(b)):
        if t in remove: continue
        k = seen.get(t, 0); seen[t] = k + 1
        out.append(repl.get((t, k), x))
    out.extend(append)
    return box(b[4:8], b''.join(out))

def stts_read(b):
    p = b[8:]; n = int.from_bytes(p[4:8], 'big')
    return p[:4], [list(struct.unpack('>II', p[8+i*8:16+i*8])) for i in range(n)]

def stts_write(v, a): return box(b'stts', v + struct.pack('>I', len(a)) + b''.join(struct.pack('>II', *x) for x in a))

def stsc_read(b):
    p = b[8:]; n = int.from_bytes(p[4:8], 'big')
    return p[:4], [list(struct.unpack('>III', p[8+i*12:20+i*12])) for i in range(n)]

def stsc_write(v, a): return box(b'stsc', v + struct.pack('>I', len(a)) + b''.join(struct.pack('>III', *x) for x in a))

def stco_read(b):
    p = b[8:]; n = int.from_bytes(p[4:8], 'big')
    return p[:4], list(struct.unpack('>' + ('I' * n), p[8:8+4*n]))

def stco_write(v, a): return box(b'stco', v + struct.pack('>I', len(a)) + b''.join(struct.pack('>I', x) for x in a))

def stsz_read(b):
    p = b[8:]; ss = int.from_bytes(p[4:8], 'big'); n = int.from_bytes(p[8:12], 'big')
    if ss: return p[:4], [ss] * n
    return p[:4], list(struct.unpack('>' + ('I' * n), p[12:12+4*n]))

def stsz_write(v, a): return box(b'stsz', v + b'\0\0\0\0' + struct.pack('>I', len(a)) + b''.join(struct.pack('>I', x) for x in a))

def get_handler(t): return child(child(t, b'mdia'), b'hdlr')[16:20]

def pop_or_dec_last_sample(tt):
    if tt:
        if tt[-1][0] > 1:
            tt[-1][0] -= 1
        else:
            tt.pop()

def patch_video_descriptors(stbl, video_timescale, video_duration, orig_compressor_name=None):
    stsd = child(stbl, b'stsd')
    entries = []
    for t, i, n, h, x in boxes(stsd, 16, len(stsd)):
        if t != b'avc1':
            entries.append(x)
            continue
        
        subs = boxes(x, 86, len(x))
        has_colr = any(st == b'colr' for st, _, _, _, _ in subs)
        has_btrt = any(st == b'btrt' for st, _, _, _, _ in subs)
        
        children = []
        for st, si, sn, sh, sx in subs:
            children.append(sx)
            if st == b'avcC' and not has_colr:
                children.append(bytes.fromhex('00000013636f6c726e636c7800010001000100'))
                has_colr = True
                
        if not has_btrt:
            _, original_sizes = stsz_read(child(stbl, b'stsz'))
            video_bits = sum(original_sizes) * 8
            calc_br = (video_bits * video_timescale) // video_duration
            btrt_box = struct.pack('>I4sIII', 20, b'btrt', 0, calc_br, calc_br)
            children.append(btrt_box)
            
        avc1_payload = bytearray(x[8:86])
        if orig_compressor_name and len(orig_compressor_name) == 32:
            avc1_payload[42:74] = orig_compressor_name
            
        new_avc1_payload = bytes(avc1_payload) + b''.join(children)
        entries.append(struct.pack('>I4s', 8 + len(new_avc1_payload), b'avc1') + new_avc1_payload)
    new_stsd_payload = stsd[8:16] + b''.join(entries)
    stsd = struct.pack('>I4s', 8 + len(new_stsd_payload), b'stsd') + new_stsd_payload
    return rebuild(stbl, {(b'stsd', 0): stsd})

def patch_mp4a_btrt(stbl, btrt_value):
    stsd = child(stbl, b'stsd')
    entries = []
    for t, i, n, h, x in boxes(stsd, 16, len(stsd)):
        if t != b'mp4a':
            entries.append(x)
            continue
        
        old_avg = btrt_value
        has_btrt = False
        for ct, ci, cn, ch, cx in boxes(x, 36, len(x)):
            if ct == b'btrt':
                has_btrt = True
                if len(cx) >= 20:
                    old_avg = int.from_bytes(cx[16:20], 'big')
            elif ct == b'esds' and not has_btrt:
                pos = cx.find(b'\x04')
                if pos != -1 and len(cx) >= pos + 15:
                    avg_br = int.from_bytes(cx[pos+11:pos+15], 'big')
                    if avg_br > 0:
                        old_avg = avg_br
                        
        subs = []
        for ct, ci, cn, ch, cx in boxes(x, 36, len(x)):
            if ct == b'btrt': continue
            subs.append(cx)
        btrt = struct.pack('>I4sIII', 20, b'btrt', 0, old_avg, old_avg)
        subs.append(btrt)
        new_mp4a_payload = x[8:36] + b''.join(subs)
        entries.append(struct.pack('>I4s', 8 + len(new_mp4a_payload), b'mp4a') + new_mp4a_payload)
    new_stsd_payload = stsd[8:16] + b''.join(entries)
    stsd = struct.pack('>I4s', 8 + len(new_stsd_payload), b'stsd') + new_stsd_payload
    return rebuild(stbl, {(b'stsd', 0): stsd})

def calc_stts_remainder(moov, audio, orig_moov=None):
    mv_timescale = int.from_bytes(child(moov, b'mvhd')[20:24], 'big')
    mdia = child(audio, b'mdia')
    md = child(mdia, b'mdhd')[8:]
    md_version = md[0]
    audio_timescale = struct.unpack('>I', md[20:24])[0] if md_version == 1 else struct.unpack('>I', md[12:16])[0]

    target_duration = None
    if orig_moov:
        try:
            o_audio = next((t for t in [x[4] for x in boxes(orig_moov, 8, len(orig_moov)) if x[0] == b'trak'] if get_handler(t) == b'soun'), None)
            if o_audio:
                o_mvhd = child(orig_moov, b'mvhd')[8:]
                o_mv_ts = struct.unpack('>I', o_mvhd[12:16])[0] if o_mvhd[0] == 0 else struct.unpack('>I', o_mvhd[20:24])[0]
                o_mdia = child(o_audio, b'mdia')
                o_mdhd = child(o_mdia, b'mdhd')[8:]
                o_a_ts = struct.unpack('>I', o_mdhd[12:16])[0] if o_mdhd[0] == 0 else struct.unpack('>I', o_mdhd[20:24])[0]
                o_elst = child(child(o_audio, b'edts'), b'elst')[8:]
                o_v = o_elst[0]
                o_cnt = struct.unpack('>I', o_elst[4:8])[0]
                if o_v == 1:
                    o_entries = [(struct.unpack('>Q', o_elst[8+i*20:16+i*20])[0], struct.unpack('>q', o_elst[16+i*20:24+i*20])[0]) for i in range(o_cnt)]
                else:
                    o_entries = [(struct.unpack('>I', o_elst[8+i*12:12+i*12])[0], struct.unpack('>i', o_elst[12+i*12:16+i*12])[0]) for i in range(o_cnt)]
                empty_dur = sum(sd for sd, mt in o_entries if mt < 0)
                play_dur = sum(sd for sd, mt in o_entries if mt >= 0)
                media_time = next((mt for sd, mt in o_entries if mt >= 0), 0)
                net_dur = max(0, play_dur - empty_dur)
                scaled = net_dur * o_a_ts
                target_duration = (scaled + o_mv_ts // 2) // o_mv_ts + media_time
        except Exception:
            pass

    segment_duration = None
    try:
        edts = child(audio, b'edts')
        elst = child(edts, b'elst')
        ep = elst[8:]
        elst_version = ep[0]
        entry_count = struct.unpack('>I', ep[4:8])[0]
        if elst_version == 1:
            entries = [(struct.unpack('>Q', ep[8+i*20:16+i*20])[0], struct.unpack('>q', ep[16+i*20:24+i*20])[0]) for i in range(entry_count)]
        else:
            entries = [(struct.unpack('>I', ep[8+i*12:12+i*12])[0], struct.unpack('>i', ep[12+i*12:16+i*12])[0]) for i in range(entry_count)]
        segment_duration = next((sd for sd, mt in entries if mt >= 0), None)
        if target_duration is None:
            empty_dur = sum(sd for sd, mt in entries if mt < 0)
            play_dur = sum(sd for sd, mt in entries if mt >= 0)
            media_time = next((mt for sd, mt in entries if mt >= 0), 0)
            net_dur = max(0, play_dur - empty_dur)
            scaled = net_dur * audio_timescale
            target_duration = (scaled + mv_timescale // 2) // mv_timescale + media_time
    except Exception:
        pass

    stbl = child(child(mdia, b'minf'), b'stbl')
    _, tt = stts_read(child(stbl, b'stts'))
    current_duration = sum(count * dur for count, dur in tt)
    last_sample_dur = tt[-1][1] if tt else 1024

    if target_duration is None:
        target_duration = current_duration
    if segment_duration is None:
        segment_duration = round(current_duration * mv_timescale / audio_timescale)

    remainder = target_duration - (current_duration - last_sample_dur)
    return remainder, segment_duration

def patch_track_common(t, delta, newid=None, newdur=None):
    t = rebuild(t, remove=(b'edts',))
    tk = bytearray(child(t, b'tkhd'))
    if newid is not None:
        tk[20:24] = struct.pack('>I', newid)
    if newdur is not None:
        tk[28:32] = struct.pack('>I', newdur)
    t = rebuild(t, {(b'tkhd', 0): bytes(tk)})
    mdia = child(t, b'mdia'); minf = child(mdia, b'minf'); stbl = child(minf, b'stbl')
    v, offs = stco_read(child(stbl, b'stco')); offs = [x + delta for x in offs]
    stbl = rebuild(stbl, {(b'stco', 0): stco_write(v, offs)})
    minf = rebuild(minf, {(b'stbl', 0): stbl})
    mdia = rebuild(mdia, {(b'minf', 0): minf})
    return rebuild(t, {(b'mdia', 0): mdia})

def make_audio3(src, synth_count, synth_offset, delta, stts_remainder, btrt_value, newdur=None):
    t = rebuild(src, remove=(b'edts',))
    tk = bytearray(child(t, b'tkhd'))
    tk[20:24] = struct.pack('>I', 3)
    if newdur is not None:
        tk[28:32] = struct.pack('>I', newdur)
    t = rebuild(t, {(b'tkhd', 0): bytes(tk)})
    mdia = child(t, b'mdia'); minf = child(mdia, b'minf'); stbl = child(minf, b'stbl')
    
    v, tt = stts_read(child(stbl, b'stts'))
    pop_or_dec_last_sample(tt)
    tt.append([1, stts_remainder])
    tt.append([synth_count, 1])
    
    mdhd = bytearray(child(mdia, b'mdhd'))
    mdhd[24:28] = struct.pack('>I', sum(count * dur for count, dur in tt))
    mdia = rebuild(mdia, {(b'mdhd', 0): bytes(mdhd)})
    
    minf = child(mdia, b'minf'); stbl = child(minf, b'stbl')
    stbl = rebuild(stbl, {(b'stts', 0): stts_write(v, tt)})
    
    v, sc = stsc_read(child(stbl, b'stsc'))
    existing_chunks = len(stco_read(child(stbl, b'stco'))[1])
    sc.append([existing_chunks + 1, synth_count, 1])
    stbl = rebuild(stbl, {(b'stsc', 0): stsc_write(v, sc)})
    
    v, ss = stsz_read(child(stbl, b'stsz')); ss += [8] * synth_count
    stbl = rebuild(stbl, {(b'stsz', 0): stsz_write(v, ss)})
    
    v, offs = stco_read(child(stbl, b'stco')); offs = [x + delta for x in offs]; offs.append(synth_offset)
    stbl = rebuild(stbl, {(b'stco', 0): stco_write(v, offs)})
    
    stbl = patch_mp4a_btrt(stbl, btrt_value)
    minf = rebuild(minf, {(b'stbl', 0): stbl}); mdia = rebuild(mdia, {(b'minf', 0): minf})
    return rebuild(t, {(b'mdia', 0): mdia})

def patch_moov_payload(moov_bytes, mdat_start, mdat_size, orig_compressor_name=None, orig_duration=None, orig_moov=None):
    moov = moov_bytes
    tracks = [x[4] for x in boxes(moov, 8, len(moov)) if x[0] == b'trak']
    video = next(t for t in tracks if get_handler(t) == b'vide')
    audio = next(t for t in tracks if get_handler(t) == b'soun')
    stts_remainder, segment_dur = calc_stts_remainder(moov, audio, orig_moov=orig_moov)
    stbl = child(child(child(audio, b'mdia'), b'minf'), b'stbl')
    real = len(stsz_read(child(stbl, b'stsz'))[1])
    synth = real * 9

    _, original_sizes = stsz_read(child(stbl, b'stsz'))
    audio_bits = sum(original_sizes) * 8
    audio_mdhd = child(child(audio, b'mdia'), b'mdhd')
    audio_timescale = struct.unpack('>I', audio_mdhd[20:24])[0]
    _, tt_orig = stts_read(child(stbl, b'stts'))
    pop_or_dec_last_sample(tt_orig)
    tt_orig.append([1, stts_remainder])
    new_audio_duration = sum(count * dur for count, dur in tt_orig)
    btrt_value = (audio_bits * audio_timescale) // new_audio_duration

    v_mdia = child(video, b'mdia')
    v_mdhd = bytearray(child(v_mdia, b'mdhd'))
    video_timescale = struct.unpack('>I', v_mdhd[20:24])[0]
    v_stbl = child(child(v_mdia, b'minf'), b'stbl')
    _, v_tt = stts_read(child(v_stbl, b'stts'))
    v_stts_dur = sum(c * d for c, d in v_tt)
    v_mdhd[24:28] = struct.pack('>I', v_stts_dur)
    
    # Ensure video stbl has colr, btrt, and preserves original compressor name if present
    v_stbl = patch_video_descriptors(v_stbl, video_timescale, v_stts_dur, orig_compressor_name)
    v_minf = child(v_mdia, b'minf')
    v_minf = rebuild(v_minf, {(b'stbl', 0): v_stbl})
    v_mdia = rebuild(v_mdia, {(b'mdhd', 0): bytes(v_mdhd), (b'minf', 0): v_minf})
    video = rebuild(video, {(b'mdia', 0): v_mdia})

    def build(delta, synth_offset):
        outparts = []
        audio_added = False
        for t, i, n, h, x in boxes(moov, 8, len(moov)):
            target_dur = orig_duration if orig_duration is not None else segment_dur
            if t == b'mvhd':
                mv = bytearray(x)
                if target_dur is not None:
                    mv[24:28] = struct.pack('>I', target_dur)
                mv[-4:] = struct.pack('>I', 4)
                outparts.append(bytes(mv))
            elif t == b'trak':
                hdl = get_handler(x)
                if hdl == b'vide':
                    outparts.append(patch_track_common(video, delta))
                elif hdl == b'soun':
                    outparts.append(patch_track_common(x, delta, newdur=(orig_duration if orig_duration is not None else segment_dur)))
                    original_audio = outparts[-1]
                    mdia_original = child(original_audio, b'mdia')
                    minf_original = child(mdia_original, b'minf')
                    stbl_original = child(minf_original, b'stbl')
                    v, tt = stts_read(child(stbl_original, b'stts'))
                    pop_or_dec_last_sample(tt)
                    tt.append([1, stts_remainder])
                    mdhd_original = bytearray(child(mdia_original, b'mdhd'))
                    mdhd_original[24:28] = struct.pack('>I', sum(count * dur for count, dur in tt))
                    mdia_original = rebuild(mdia_original, {(b'mdhd', 0): bytes(mdhd_original)})
                    stbl_original = patch_mp4a_btrt(stbl_original, btrt_value)
                    stbl_original = rebuild(stbl_original, {(b'stts', 0): stts_write(v, tt)})
                    minf_original = rebuild(minf_original, {(b'stbl', 0): stbl_original})
                    mdia_original = rebuild(mdia_original, {(b'minf', 0): minf_original})
                    outparts[-1] = rebuild(original_audio, {(b'mdia', 0): mdia_original})
                    if not audio_added:
                        outparts.append(make_audio3(x, synth, synth_offset, delta, stts_remainder, btrt_value, newdur=(orig_duration if orig_duration is not None else segment_dur)))
                        audio_added = True
                else:
                    outparts.append(x)
            elif t == b'udta':
                outparts.append(SITE_UDTA)
            else:
                outparts.append(x)
        if not any(x[4:8] == b'udta' for x in outparts):
            outparts.append(SITE_UDTA)
        return box(b'moov', b''.join(outparts))

    provisional = build(0, 0)
    final_mdat_start = 32 + len(provisional)
    delta = final_mdat_start - mdat_start
    synth_offset = final_mdat_start + mdat_size
    final_moov = build(delta, synth_offset)
    final_mdat_start = 32 + len(final_moov)
    delta = final_mdat_start - mdat_start
    synth_offset = final_mdat_start + mdat_size
    final_moov = build(delta, synth_offset)
    return final_moov, synth

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            req = json.loads(body.decode('utf-8'))

            moov_b64 = req.get('moov')
            mdat_start = int(req.get('mdat_start', 0))
            mdat_size = int(req.get('mdat_size', 0))
            orig_cname_hex = req.get('orig_compressor')
            orig_cname = bytes.fromhex(orig_cname_hex) if orig_cname_hex else None
            orig_duration = req.get('orig_duration')
            if orig_duration is not None:
                orig_duration = int(orig_duration)

            orig_moov_b64 = req.get('orig_moov')
            orig_moov = base64.b64decode(orig_moov_b64) if orig_moov_b64 else None

            if not moov_b64 or mdat_size <= 0:
                raise ValueError('Invalid request parameters: moov and mdat_size are required')

            moov_bytes = base64.b64decode(moov_b64)
            patched_moov, synth_count = patch_moov_payload(moov_bytes, mdat_start, mdat_size, orig_cname, orig_duration, orig_moov=orig_moov)

            resp_data = {
                'status': 'success',
                'patched_moov': base64.b64encode(patched_moov).decode('utf-8'),
                'synth_count': synth_count
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(resp_data).encode('utf-8'))

        except Exception as e:
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            err_resp = {'status': 'error', 'message': str(e)}
            self.wfile.write(json.dumps(err_resp).encode('utf-8'))
