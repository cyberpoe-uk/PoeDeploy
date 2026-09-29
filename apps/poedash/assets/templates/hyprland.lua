-- PoeDash startup and reserved home workspace (Hyprland Lua).
hl.on("hyprland.start", function()
    hl.exec_cmd(@@START@@)
end)

-- Workspace 1 belongs to the Eww layer surface, not application windows.
hl.unbind("SUPER + SHIFT + 1")
hl.unbind("SUPER + SHIFT + ampersand") -- French keyboard equivalent

local previous_workspace = {}
local pending_return = {}

local function protect_home(window, follow_new_window)
    if not window or not window.workspace then return end
    local address = window.address
    if not address then return end
    local workspace = window.workspace
    if workspace.id ~= 1 then
        previous_workspace[address] = workspace.name
        return
    end
    if pending_return[address] then return end
    local destination = previous_workspace[address] or "2"
    -- Defer until Hyprland has completed the original map/move operation.
    pending_return[address] = hl.timer(function()
        pending_return[address] = nil
        local current = hl.get_window("address:" .. address)
        if current and current.workspace and current.workspace.id == 1 then
            hl.dispatch(hl.dsp.window.move({
                window = current,
                workspace = destination,
                silent = not follow_new_window,
            }))
        end
    end, { timeout = 1, type = "oneshot" })
end

hl.on("window.move_to_workspace", function(window)
    protect_home(window, false)
end)
hl.on("window.open", function(window)
    protect_home(window, true)
end)
hl.on("window.close", function(window)
    if not window or not window.address then return end
    previous_workspace[window.address] = nil
    if pending_return[window.address] then
        pending_return[window.address]:set_enabled(false)
        pending_return[window.address] = nil
    end
end)
-- Seed history after reload and clear any application windows already on home.
for _, window in ipairs(hl.get_windows()) do
    protect_home(window, false)
end
