// One-shot transfer of the image tool's new motif onto unchanged ancestral rock.
// Run from the repository root; requires the original generation at wall-v9.png.
const fs = require('node:fs');
const crypto = require('node:crypto');
const media = require('./png_codec.cjs');
const hash = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const source = 'artifacts/line-3/wall-v8.png';
const destination = 'artifacts/line-3/wall-v9.png';
const oldBytes = fs.readFileSync(source);
if (hash(oldBytes) !== '479a29d225f1860f2d235ec8f2d9b3ab4abbd39ad7764dc496ed623a55d15c8c')
  throw Error('Inherited wall differs from its unchanged record');
const generatedBytes = fs.readFileSync(destination);
if (hash(generatedBytes) !== 'a450c25696371bb97270b387c34479717045dc481452701dbd1bd779618e1d8b')
  throw Error('Original generation required; never rerun on the finished wall');
const old = media.decode(oldBytes), generated = media.decode(generatedBytes);
const out = {...old, pixels: Buffer.from(old.pixels)};
const box = [596, 440, 143, 66];
const sourceBox = [522, 450, 176, 76];
function inside(x, y, polygon) {
  let result = false;
  for (let i=0,j=polygon.length-1;i<polygon.length;j=i++) {
    const [a,b]=polygon[i], [c,d]=polygon[j];
    if ((b>y)!==(d>y) && x<(c-a)*(y-b)/(d-b)+a) result=!result;
  }
  return result;
}
const stones = [
  [[527,518],[529,479],[534,463],[543,453],[550,457],[558,475],[561,518]],
  [[655,520],[658,481],[662,466],[670,456],[678,456],[686,469],[692,519]],
];
let changed=0;
for(let dy=0;dy<box[3];dy++) for(let dx=0;dx<box[2];dx++) {
  const sx=Math.round(sourceBox[0]+dx*sourceBox[2]/box[2]);
  const sy=Math.round(sourceBox[1]+dy*sourceBox[3]/box[3]);
  const si=(sy*generated.width+sx)*3;
  const [r,g,b]=generated.pixels.subarray(si,si+3);
  const stone=stones.some(p=>inside(sx,sy,p));
  const bowl=(Math.hypot((sx-609)/39,(sy-486)/12)<=1.12) ||
    (sy>=486 && Math.hypot((sx-609)/37,(sy-486)/33)<=1.07);
  const pebble=Math.hypot((sx-599)/10,(sy-488)/9)<1 ||
    Math.hypot((sx-616)/10,(sy-488)/9)<1;
  const charcoal=(stone || bowl) && r<113 && g<88 && b<64;
  const yellow=stone && r>115 && r-g>30 && g-b>24 && g>68;
  const red=pebble && r>g*1.65 && r-b>45 && g<108;
  if(!charcoal && !yellow && !red) continue;
  const color=charcoal?[43,32,22]:red?[145,61,27]:[185,119,43];
  const alpha=charcoal?Math.min(.84,(150-r)/90):red?.76:.62;
  const i=((box[1]+dy)*old.width+box[0]+dx)*3;
  for(let c=0;c<3;c++) out.pixels[i+c]=Math.round(old.pixels[i+c]*(1-alpha)+color[c]*alpha);
  if(!old.pixels.subarray(i,i+3).equals(out.pixels.subarray(i,i+3))) changed++;
}
if(changed<1000) throw Error('Expected new pigment missing; original generation required');
let outside=0;
const protectedHash=crypto.createHash('sha256');
for(let y=0;y<old.height;y++) for(let x=0;x<old.width;x++) {
  if(x>=box[0] && x<box[0]+box[2] && y>=box[1] && y<box[1]+box[3]) continue;
  const i=(y*old.width+x)*3;
  if(!old.pixels.subarray(i,i+3).equals(out.pixels.subarray(i,i+3))) outside++;
  protectedHash.update(out.pixels.subarray(i,i+3));
}
if(outside) throw Error('Pixels changed outside additive patch');
const bytes=media.encode(out), preview=media.thumbnail(out);
if(!media.decode(bytes).pixels.equals(out.pixels) || preview.length>=100000) throw Error('Encoding check failed');
fs.writeFileSync(destination,bytes);
// Replace the link itself, never write through it to an ancestral wall.
if(fs.existsSync('artifacts/line-3/wall.png')) fs.unlinkSync('artifacts/line-3/wall.png');
fs.symlinkSync('wall-v9.png','artifacts/line-3/wall.png');
fs.writeFileSync('dist/line-3/28.jpg',preview,{flag:'wx'});
const report={source,source_sha256:hash(oldBytes),generated_edit_sha256:hash(generatedBytes),
  output_sha256:hash(bytes),patch_xywh:box,generated_source_xywh:sourceBox,
  changed_pixels:changed,changed_pixels_outside_patch:outside,
  protected_rgb_sha256:protectedHash.digest('hex'),
  method:'Only generated new pigment selected and placed on bare central rock; all other RGB pixels retained.',
  png_dimensions:[old.width,old.height],png_bytes:bytes.length,
  jpeg_dimensions:[512,512],jpeg_bytes:preview.length};
fs.writeFileSync('line-3/asset-build/preservation-28.json',JSON.stringify(report,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify(report,null,2));
