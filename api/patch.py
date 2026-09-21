from http.server import BaseHTTPRequestHandler
import json
import base64
import struct

SITE_UDTA = bytes.fromhex(
    '0000010e75647461'
    '0000008d6d657461000000850000002168646c7200000000000000006d6469726170706c'
    '00000000000000000000000060696c737400000025a9746f6f0000001d6461746100000001000000004c61766635392e32372e313030'
    '00000033a9636d740000002b6461746100000001000000005061746368656420627920436f6d7072657373626173652e636f6d'
    '000000796d657461000000000000002168646c7200000000000000006d64697200000000000000000000000000000000116e616d652e67672f6d61736b61'
    '0000003b696c737400000033a9636d740000002b6461746100000001000000005061746368656420627920436f6d7072657373626173652e636f6d'
)

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

def patch_video_descriptors(stbl, video_timescale, video_duration):
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
                # Insert BT.709 nclx colr box right after avcC
                children.append(bytes.fromhex('00000013636f6c726e636c7800010001000100'))
                has_colr = True
                
        if not has_btrt:
            # Calculate video bitrate
            _, original_sizes = stsz_read(child(stbl, b'stsz'))
            video_bits = sum(original_sizes) * 8
            calc_br = (video_bits * video_timescale) // video_duration
            btrt_box = struct.pack('>I4sIII', 20, b'btrt', 0, calc_br, calc_br)
            children.append(btrt_box)
            
        new_avc1_payload = x[8:86] + b''.join(children)
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
                old_avg = struct.unpack('>I', cx[16:20])[0]
                has_btrt = True
                break
        if not has_btrt:
            for ct, ci, cn, ch, cx in boxes(x, 36, len(x)):
                if ct == b'esds' and len(cx) >= 38 and cx[20] == 0x04:
                    old_avg = struct.unpack('>I', cx[34:38])[0]
                    break

        max_br = max(old_avg, btrt_value)
        avg_br = btrt_value

        children = []
        for ct, ci, cn, ch, cx in boxes(x, 36, len(x)):
            if ct == b'btrt':
                bt = bytearray(cx)
                bt[12:16] = struct.pack('>I', max_br)
                bt[16:20] = struct.pack('>I', avg_br)
                children.append(bytes(bt))
            elif ct == b'esds':
                es = bytearray(cx)
                if len(es) >= 38 and es[20] == 0x04:
                    es[30:34] = struct.pack('>I', max_br)
                    es[34:38] = struct.pack('>I', avg_br)
                children.append(bytes(es))
            else:
                children.append(cx)
                
        if not has_btrt:
            children.append(struct.pack('>I4sIII', 20, b'btrt', 0, max_br, avg_br))
            
        new_mp4a_payload = x[8:36] + b''.join(children)
        entries.append(struct.pack('>I4s', 8 + len(new_mp4a_payload), b'mp4a') + new_mp4a_payload)
    new_stsd_payload = stsd[8:16] + b''.join(entries)
    stsd = struct.pack('>I4s', 8 + len(new_stsd_payload), b'stsd') + new_stsd_payload
    return rebuild(stbl, {(b'stsd', 0): stsd})

def calc_stts_remainder(moov, audio):
    mvhd = child(moov, b'mvhd')
    mv = mvhd[8:]
    mv_version = mv[0]
    mv_timescale = struct.unpack('>I', mv[20:24])[0] if mv_version == 1 else struct.unpack('>I', mv[12:16])[0]

    mdia = child(audio, b'mdia')
    mdhd = child(mdia, b'mdhd')
    md = mdhd[8:]
    md_version = md[0]
    audio_timescale = struct.unpack('>I', md[20:24])[0] if md_version == 1 else struct.unpack('>I', md[12:16])[0]

    edts = child(audio, b'edts')
    elst = child(edts, b'elst')
    ep = elst[8:]
    elst_version = ep[0]
    entry_count = struct.unpack('>I', ep[4:8])[0]
    if entry_count < 1: raise ValueError('audio elst has no entries')
    if elst_version == 1:
        segment_duration = struct.unpack('>Q', ep[8:16])[0]
        media_time = struct.unpack('>q', ep[16:24])[0]
    else:
        segment_duration = struct.unpack('>I', ep[8:12])[0]
        media_time = struct.unpack('>i', ep[12:16])[0]

    stbl = child(child(mdia, b'minf'), b'stbl')
    _, tt = stts_read(child(stbl, b'stts'))
    current_duration = sum(count * dur for count, dur in tt)
    last_sample_dur = tt[-1][1] if tt else 1024

    scaled = segment_duration * audio_timescale
    target_duration = (scaled + mv_timescale // 2) // mv_timescale + media_time
    return target_duration - (current_duration - last_sample_dur)

def patch_track_common(t, delta, newid=None):
    t = rebuild(t, remove=(b'edts',))
    if newid is not None:
        tk = bytearray(child(t, b'tkhd')); tk[20:24] = struct.pack('>I', newid)
        t = rebuild(t, {(b'tkhd', 0): bytes(tk)})
    mdia = child(t, b'mdia'); minf = child(mdia, b'minf'); stbl = child(minf, b'stbl')
    v, offs = stco_read(child(stbl, b'stco')); offs = [x + delta for x in offs]
    stbl = rebuild(stbl, {(b'stco', 0): stco_write(v, offs)})
    minf = rebuild(minf, {(b'stbl', 0): stbl})
    mdia = rebuild(mdia, {(b'minf', 0): minf})
    return rebuild(t, {(b'mdia', 0): mdia})

def make_audio3(src, synth_count, synth_offset, delta, stts_remainder, btrt_value):
    t = rebuild(src, remove=(b'edts',))
    tk = bytearray(child(t, b'tkhd')); tk[20:24] = struct.pack('>I', 3); t = rebuild(t, {(b'tkhd', 0): bytes(tk)})
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

def patch_moov_payload(moov_bytes, mdat_start, mdat_size):
    moov = moov_bytes
    tracks = [x[4] for x in boxes(moov, 8, len(moov)) if x[0] == b'trak']
    video = next(t for t in tracks if get_handler(t) == b'vide')
    audio = next(t for t in tracks if get_handler(t) == b'soun')
    stts_remainder = calc_stts_remainder(moov, audio)
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
    
    # Ensure video stbl has colr and btrt
    v_stbl = patch_video_descriptors(v_stbl, video_timescale, v_stts_dur)
    v_minf = child(v_mdia, b'minf')
    v_minf = rebuild(v_minf, {(b'stbl', 0): v_stbl})
    v_mdia = rebuild(v_mdia, {(b'mdhd', 0): bytes(v_mdhd), (b'minf', 0): v_minf})
    video = rebuild(video, {(b'mdia', 0): v_mdia})

    def build(delta, synth_offset):
        outparts = []
        audio_added = False
        for t, i, n, h, x in boxes(moov, 8, len(moov)):
            if t == b'mvhd':
                mv = bytearray(x); mv[-4:] = struct.pack('>I', 4); outparts.append(bytes(mv))
            elif t == b'trak':
                hdl = get_handler(x)
                if hdl == b'vide':
                    outparts.append(patch_track_common(video, delta))
                elif hdl == b'soun':
                    outparts.append(patch_track_common(x, delta))
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
                        outparts.append(make_audio3(x, synth, synth_offset, delta, stts_remainder, btrt_value))
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

            if not moov_b64 or mdat_size <= 0:
                raise ValueError('Invalid request parameters: moov and mdat_size are required')

            moov_bytes = base64.b64decode(moov_b64)
            patched_moov, synth_count = patch_moov_payload(moov_bytes, mdat_start, mdat_size)

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
