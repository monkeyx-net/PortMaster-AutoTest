local function read_file(path)
    local f = io.open(path, "rb")
    if not f then return nil end
    local data = f:read("*all")
    f:close()
    return data
end

local function fb_size()
    local s = read_file("/sys/class/graphics/fb0/virtual_size")
    if s then
        local w, h = s:match("(%d+),(%d+)")
        if w then return tonumber(w), tonumber(h) end
    end
    local fbset = io.popen("fbset 2>/dev/null")
    if fbset then
        local out = fbset:read("*all")
        fbset:close()
        local w, h = out:match('geometry (%d+) (%d+)')
        if w then return tonumber(w), tonumber(h) end
    end
    return 640, 480
end

local width, height = fb_size()
local fb_data = read_file("/dev/fb0")
if not fb_data then
    print("Error: could not read /dev/fb0")
    os.exit(1)
end

local img = love.image.newImageData(width, height, "bgra8", fb_data)
local out_path = arg[1] or "screenshot.png"
img:encode("png", out_path)
print("Saved " .. out_path)
os.exit(0)
