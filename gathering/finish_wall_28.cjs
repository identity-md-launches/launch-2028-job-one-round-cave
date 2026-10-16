// Preserve ancestor pixels; use the image tool's pigment only on bare lower-left rock.
const fs=require('node:fs'), crypto=require('node:crypto');
const media=require('../line-1/media/finish-wall.cjs');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const beforeBytes=fs.readFileSync('artifacts/gathering/wall-v8.png');
const generatedBytes=fs.readFileSync('artifacts/gathering/wall-v9.png');
if(sha(generatedBytes)!=='fab128c6b625b4852c3d6129c631bee7bc002fd64a75c4a458bfd9d1704fb772') throw Error('Requires original reviewed image-tool output; do not rerun on final wall');
const before=media.decode(beforeBytes), generated=media.decode(generatedBytes);
const output={...before,pixels:Buffer.from(before.pixels)};
const box=[195,900,170,150];
let changed=0,outside=0;
for(let y=box[1];y<box[1]+box[3];y++) for(let x=box[0];x<box[0]+box[2];x++) {
 const i=(y*before.width+x)*3;
 const [r,g,b]=generated.pixels.subarray(i,i+3);
 const difference=Math.max(...[0,1,2].map(c=>Math.abs(generated.pixels[i+c]-before.pixels[i+c])));
 const pigment=(r<105 && g<80 && b<62) || (r>g*1.65 && r-b>45);
 if(!pigment || difference<22) continue;
 // Keep the original stone's fine texture visible through the new pigment.
 const alpha=.82;
 for(let c=0;c<3;c++) output.pixels[i+c]=Math.round(before.pixels[i+c]*(1-alpha)+generated.pixels[i+c]*alpha);
 if(!output.pixels.subarray(i,i+3).equals(before.pixels.subarray(i,i+3))) changed++;
}
if(changed<1000) throw Error('missing mark');
const protectedHash=crypto.createHash('sha256');
for(let y=0;y<before.height;y++) for(let x=0;x<before.width;x++) {
 if(x>=box[0] && x<box[0]+box[2] && y>=box[1] && y<box[1]+box[3]) continue;
 const i=(y*before.width+x)*3,a=before.pixels.subarray(i,i+3),b=output.pixels.subarray(i,i+3);
 if(!a.equals(b)) outside++;protectedHash.update(b);
}
if(outside) throw Error('ancestor pixels changed');
const bytes=media.encode(output),jpg=media.thumbnail(output);
if(!media.decode(bytes).pixels.equals(output.pixels) || jpg.length>100000) throw Error('encoding failed');
fs.writeFileSync('artifacts/gathering/wall-v9.png',bytes);
fs.writeFileSync('dist/gathering/28.jpg',jpg);
try {fs.unlinkSync('artifacts/gathering/wall.png');} catch(e) {if(e.code!=='ENOENT') throw e;}
fs.symlinkSync('wall-v9.png','artifacts/gathering/wall.png');
const report={inherited_wall_sha256:sha(beforeBytes),generated_edit_sha256:sha(generatedBytes),output_sha256:sha(bytes),
 mark_rectangle:box,changed_pixels_inside:changed,pixels_changed_outside:outside,protected_rgb_sha256:protectedHash.digest('hex'),
 method:'Image-tool pouch pigment selected on bare rock, blended over original texture; all other pixels retained exactly.',
 png_dimensions:[before.width,before.height],png_format:'RGB PNG',jpeg_dimensions:[512,512],jpeg_bytes:jpg.length};
fs.writeFileSync('gathering/preservation-28.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
