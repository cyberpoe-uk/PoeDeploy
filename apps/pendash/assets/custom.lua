-- BEGIN PENDASH
do
local function dashboard_disabled()
    local f = io.open(os.getenv("HOME") .. "/.config/eww/disabled", "r")
    if f then f:close() return true end
    return false
end
if not dashboard_disabled() then
hl.on("hyprland.start", function()
    hl.exec_cmd(os.getenv("HOME") .. "/.config/eww/scripts/start.sh")
end)

hl.unbind("SUPER + SHIFT + 1")
hl.unbind("SUPER + SHIFT + ampersand")
local previous_workspace = {}
local pending_return = {}
local function protect_home(window, follow)
    if dashboard_disabled() then return end
    if not window or not window.workspace or not window.address then return end
    if window.workspace.id ~= 1 then previous_workspace[window.address] = window.workspace.name return end
    if pending_return[window.address] then return end
    local address = window.address
    pending_return[address] = hl.timer(function()
        pending_return[address] = nil
        local current = hl.get_window("address:" .. address)
        if not dashboard_disabled() and current and current.workspace and current.workspace.id == 1 then
            hl.dispatch(hl.dsp.window.move({window=current, workspace=previous_workspace[address] or "2", silent=not follow}))
        end
    end, {timeout=1, type="oneshot"})
end
hl.on("window.move_to_workspace", function(window) protect_home(window, false) end)
hl.on("window.open", function(window) protect_home(window, true) end)
hl.on("window.close", function(window)
    if not window or not window.address then return end
    previous_workspace[window.address] = nil
    if pending_return[window.address] then pending_return[window.address]:set_enabled(false) pending_return[window.address] = nil end
end)
for _, window in ipairs(hl.get_windows()) do protect_home(window, false) end
end
end
-- END PENDASH
