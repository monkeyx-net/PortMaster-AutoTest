-- fbshot: headless Love2D framebuffer screenshot tool.
-- Usage: love fbshot.love <output.png>
-- Reads /dev/fb0, detects pixel format via ioctl, saves PNG.
-- No window is created so the running game's display is undisturbed.

local ffi = require("ffi")
local bit = require("bit")

ffi.cdef[[
struct fb_bitfield {
    uint32_t offset;
    uint32_t length;
    uint32_t msb_right;
};

struct fb_var_screeninfo {
    uint32_t xres, yres;
    uint32_t xres_virtual, yres_virtual;
    uint32_t xoffset, yoffset;
    uint32_t bits_per_pixel;
    uint32_t grayscale;
    struct fb_bitfield red;
    struct fb_bitfield green;
    struct fb_bitfield blue;
    struct fb_bitfield transp;
    uint32_t nonstd;
    uint32_t activate;
    uint32_t height;
    uint32_t width;
    uint32_t accel_flags;
    uint32_t pixclock;
    uint32_t left_margin, right_margin;
    uint32_t upper_margin, lower_margin;
    uint32_t hsync_len, vsync_len;
    uint32_t sync;
    uint32_t vmode;
    uint32_t rotate;
    uint32_t colorspace;
    uint32_t reserved[4];
};

int  open(const char *path, int flags);
int  close(int fd);
int  ioctl(int fd, unsigned long req, void *arg);
]]

local FBIOGET_VSCREENINFO = 0x4600
local O_RDONLY            = 0

local function fb_info()
    local fd = ffi.C.open("/dev/fb0", O_RDONLY)
    if fd < 0 then return nil, "cannot open /dev/fb0" end
    local v   = ffi.new("struct fb_var_screeninfo")
    local ret = ffi.C.ioctl(fd, FBIOGET_VSCREENINFO, v)
    ffi.C.close(fd)
    if ret ~= 0 then return nil, "FBIOGET_VSCREENINFO ioctl failed" end
    return {
        w  = tonumber(v.xres),
        h  = tonumber(v.yres),
        bpp = tonumber(v.bits_per_pixel),
        ro  = tonumber(v.red.offset),
        go  = tonumber(v.green.offset),
        bo  = tonumber(v.blue.offset),
    }
end

local function die(msg)
    io.stderr:write("fbshot: " .. msg .. "\n")
    love.event.quit(1)
end

local function pixels_rgb565(raw, n)
    local band, rshift = bit.band, bit.rshift
    local t = {}
    for i = 0, n - 1 do
        local lo, hi = raw:byte(i * 2 + 1, i * 2 + 2)
        local px = lo + hi * 256
        local r  = band(rshift(px, 11), 0x1F)
        local g  = band(rshift(px,  5), 0x3F)
        local b  = band(px, 0x1F)
        t[i + 1] = string.char(
            math.floor(r * 255 / 31),
            math.floor(g * 255 / 63),
            math.floor(b * 255 / 31),
            255
        )
    end
    return table.concat(t)
end

local function pixels_32bpp(raw, n, ro, go, bo)
    -- Convert bit offsets to 1-based byte indices within each 4-byte pixel.
    -- e.g. BGRA: bo=0→1, go=8→2, ro=16→3
    local ri = math.floor(ro / 8) + 1
    local gi = math.floor(go / 8) + 1
    local bi = math.floor(bo / 8) + 1
    local t  = {}
    for i = 0, n - 1 do
        local p          = i * 4
        local c1, c2, c3, c4 = raw:byte(p + 1, p + 4)
        local ch         = {c1, c2, c3, c4}
        t[i + 1]         = string.char(ch[ri], ch[gi], ch[bi], 255)
    end
    return table.concat(t)
end

function love.load(args)
    local outpath = (args and args[1]) or "screenshot.png"

    local info, err = fb_info()
    if not info then die(err) return end

    local w, h, bpp = info.w, info.h, info.bpp
    local stride    = w * math.floor(bpp / 8)

    local f = io.open("/dev/fb0", "rb")
    if not f then die("cannot read /dev/fb0") return end
    local raw = f:read(h * stride)
    f:close()

    if not raw or #raw < h * stride then
        die("short read from /dev/fb0 (got " .. (raw and #raw or 0) .. " of " .. h * stride .. " bytes)")
        return
    end

    local pixel_data
    if bpp == 16 then
        pixel_data = pixels_rgb565(raw, w * h)
    elseif bpp == 32 then
        pixel_data = pixels_32bpp(raw, w * h, info.ro, info.go, info.bo)
    else
        die("unsupported bpp=" .. bpp) return
    end

    local imgdata  = love.image.newImageData(w, h, "rgba8", pixel_data)
    local filedata = imgdata:encode("png")

    local of = io.open(outpath, "wb")
    if not of then die("cannot write " .. outpath) return end
    of:write(filedata:getString())
    of:close()

    print("fbshot: " .. w .. "x" .. h .. " @" .. bpp .. "bpp -> " .. outpath)
    love.event.quit(0)
end

-- Required even though graphics module is disabled; keeps love.run happy.
function love.draw() end
