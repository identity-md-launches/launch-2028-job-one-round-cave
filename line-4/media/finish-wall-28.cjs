// One-time preservation assembly; run only against the raw imagegen edit.
const fs=require('node:fs'), crypto=require('node:crypto');
const {decode,encode,thumbnail}=require('../../line-1/media/finish-wall.cjs');
const sha=b=>crypto.createHash('sha256').update(b).digest('hex');
const base=fs.readFileSync('artifacts/line-4/wall-v8.png');
const previous=JSON.parse(fs.readFileSync('dist/line-4/27.json'));
if(previous.image!=='https://api.imd.fun/artifacts/'+sha(base)) throw Error('ancestor hash mismatch');
const raw=fs.readFileSync('artifacts/line-4/wall-v9.png');
const old=decode(base), gen=decode(raw), out={...old,pixels:Buffer.from(old.pixels)};
const clamp=n=>Math.max(0,Math.min(1,n));
function segment(x,y,ax,ay,bx,by) {
 const t=clamp(((x-ax)*(bx-ax)+(y-ay)*(by-ay))/((bx-ax)**2+(by-ay)**2));
 return Math.hypot(x-ax-t*(bx-ax),y-ay-t*(by-ay));
}
function mask(x,y) {
 const ring=Math.abs(Math.hypot(x-369,y-303)-15);
 const shaft=Math.min(segment(x,y,355,317,301,354),segment(x,y,301,354,319,371),
  segment(x,y,319,344,332,357));
 const head=Math.hypot(x-438,y-285);
 // The keyhole stem tapers toward the circular head.
 const stem=y>=299&&y<=360 ? Math.max(0,(y-299)*.27+8-Math.abs(x-437)) : 0;
 return Math.max(clamp((11-ring)/3),clamp((9-shaft)/3),clamp((27-head)/3),clamp(stem/3));
}
let changed=0,outside=0;
const bounds=[288,250,478,384];
for(let y=0;y<old.height;y++) for(let x=0;x<old.width;x++) {
 const at=(y*old.width+x)*3,inside=x>=bounds[0]&&x<=bounds[2]&&y>=bounds[1]&&y<=bounds[3];
 const a=inside?mask(x,y):0;
 for(let c=0;c<3;c++) out.pixels[at+c]=Math.round(old.pixels[at+c]*(1-a)+gen.pixels[at+c]*a);
 if(!out.pixels.subarray(at,at+3).equals(old.pixels.subarray(at,at+3))) {
  changed++; if(!a||!inside) outside++;
 }
}
if(changed<1000||outside) throw Error('preservation failure');
const png=encode(out), jpg=thumbnail(out);
if(!decode(png).pixels.equals(out.pixels)||jpg.length>100000) throw Error('media check failed');
fs.writeFileSync('artifacts/line-4/wall-v9.png',png);
fs.unlinkSync('artifacts/line-4/wall.png');
fs.linkSync('artifacts/line-4/wall-v9.png','artifacts/line-4/wall.png');
fs.writeFileSync('artifacts/line-4/28.jpg',jpg);
fs.linkSync('artifacts/line-4/28.jpg','dist/line-4/28.jpg');
const report={source:'artifacts/line-4/wall-v8.png',source_sha256:sha(base),generated_sha256:sha(raw),
 wall:'artifacts/line-4/wall-v9.png',canonical_wall:'artifacts/line-4/wall.png',sha256:sha(png),
 width:out.width,height:out.height,format:'PNG',mode:'RGB',bytes:png.length,
 preview:'dist/line-4/28.jpg',preview_width:512,preview_height:512,preview_format:'JPEG',preview_bytes:jpg.length,
 preview_sha256:sha(jpg),addition_bounds_inclusive:bounds,changed_pixels:changed,
 changed_pixels_outside_addition:outside,png_roundtrip_passed:true};
fs.writeFileSync('line-4/media-check-28.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report,null,2));
