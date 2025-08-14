import math
import random
import time
import sys
from collections import deque

import pygame
import os

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except Exception:
    NUMPY_AVAILABLE = False


WIDTH, HEIGHT = 1280, 720
FPS = 60

os.environ["SDL_AUDIODRIVER"] = "dummy"

STAGE_COLORS = [
    ((30, 30, 45), (70, 100, 140)),   
    ((50, 40, 30), (180, 120, 80)),   
    ((20, 80, 40), (120, 200, 120)),  
]


P1_KEYS = {
    "left": pygame.K_a,
    "right": pygame.K_d,
    "up": pygame.K_w,
    "down": pygame.K_s,
    "block": pygame.K_SPACE,
    "p1": pygame.K_f,
    "p2": pygame.K_g,
    "p3": pygame.K_h,
    "throw": pygame.K_r,  
}
P2_KEYS = {
    "left": pygame.K_LEFT,
    "right": pygame.K_RIGHT,
    "up": pygame.K_UP,
    "down": pygame.K_DOWN,
    "block": pygame.K_RSHIFT,
    "p1": pygame.K_KP1,
    "p2": pygame.K_KP2,
    "p3": pygame.K_KP3,
    "throw": pygame.K_KP0,
}


GRAVITY = 1600  
GROUND_Y = HEIGHT - 140
STAGE_BOUNDS = (80, WIDTH - 80)
ROUND_TIME = 60  


SAMPLE_RATE = 44100


def clamp(n, a, b):
    return max(a, min(b, n))

def sign(x): return 1 if x >= 0 else -1

def now(): return pygame.time.get_ticks() / 1000.0


def generate_tone(freq=440.0, duration=0.2, volume=0.2, sample_rate=SAMPLE_RATE):
    
    if not NUMPY_AVAILABLE:
        
        silent = b'\x00' * 100
        return pygame.mixer.Sound(buffer=silent)

    
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    wave = np.sin(freq * t * 2 * np.pi)

   
    env = np.ones_like(wave)
    attack = int(0.01 * sample_rate)
    release = int(0.04 * sample_rate)
    env[:attack] = np.linspace(0, 1, attack)
    env[-release:] = np.linspace(1, 0, release)
    wave *= env

    
    audio = (wave * (2**15 - 1) * volume).astype(np.int16)

    
    mixer_init = pygame.mixer.get_init()
    channels = mixer_init[2] if mixer_init else 1

    if channels > 1:
       
        audio = np.tile(audio.reshape(-1, 1), (1, channels))

    return pygame.sndarray.make_sound(audio)




def play_click():
    if NUMPY_AVAILABLE:
        s = generate_tone(freq=880, duration=0.06, volume=0.12)
        s.play()
    else:
        
        pass


class Button:
    def __init__(self, rect, text, font, callback=None):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.font = font
        self.callback = callback
        self.hover = False

    def draw(self, surf):
        color = (220, 220, 220) if self.hover else (180, 180, 180)
        pygame.draw.rect(surf, (20, 20, 20), self.rect, border_radius=8)
        pygame.draw.rect(surf, color, self.rect.inflate(-6, -6), border_radius=6)
        txt = self.font.render(self.text, True, (10, 10, 10))
        surf.blit(txt, txt.get_rect(center=self.rect.center))

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.hover:
            if self.callback:
                self.callback()
                play_click()


class Animation:
    
    def __init__(self, name, duration):
        self.name = name
        self.duration = duration
        self.t = 0.0
        self.done = False

    def start(self):
        self.t = 0.0
        self.done = False

    def update(self, dt):
        self.t += dt
        if self.t >= self.duration:
            self.done = True

    def progress(self):
        return clamp(self.t / self.duration, 0.0, 1.0)

class Fighter:
    
    def __init__(self, name, x, facing=1, color=(220, 50, 50), stats=None, controls=None, is_ai=False):
        self.name = name
        self.x = x
        self.y = GROUND_Y
        self.facing = facing  
        self.vx = 0.0
        self.vy = 0.0
        self.width = 56
        self.height = 120
        self.grounded = True
        self.crouching = False
        self.blocking = False
        self.jumping = False
        self.stunned = False
        self.hitstun = 0.0
        self.health = 1000
        self.max_health = 1000
        self.combo_counter = 0
        self.color = color
        self.outline = (10, 10, 10)
        
        self.state = "idle"  
        self.state_timer = 0.0
        self.anim = None
        self.attack_queue = deque()
        self.on_ground = True
        self.friction = 10.0
        self.is_ai = is_ai
        self.controls = controls
        # Stats
        default_stats = {
            "speed": 360.0,
            "jump_power": 620.0,
            "attack_damage": 80,
            "throw_damage": 140,
            "defense": 0.8,  
            "reach": 48,
            "weight": 1.0,
        }
        self.stats = default_stats
        if stats:
            self.stats.update(stats)
        
        self.attacks = {
            "jab": (0.06, 0.08, 0.26, int(self.stats["attack_damage"] * 0.9), 0.18, 180),
            "strong": (0.12, 0.12, 0.36, int(self.stats["attack_damage"] * 1.3), 0.28, 260),
            "low": (0.14, 0.10, 0.4, int(self.stats["attack_damage"] * 0.8), 0.24, 140),
            "roundhouse": (0.18, 0.14, 0.44, int(self.stats["attack_damage"] * 1.6), 0.36, 320),
            "throw": (0.1, 0.02, 0.4, self.stats["throw_damage"], 0.5, 360),
            "special": (0.28, 0.16, 0.6, int(self.stats["attack_damage"] * 2.0), 0.6, 420),
        }
        
        self.anim_timer = 0.0
        
        self.offset_x = 0
        self.offset_y = 0
        
        self.air_time = 0.0

    def rect(self):
        h = self.height
        w = self.width
        return pygame.Rect(self.x - w//2, self.y - h, w, h)

    def feet_rect(self):
        r = self.rect()
        return pygame.Rect(r.left + 8, r.bottom - 6, r.width - 16, 6)

    def update(self, dt, opponent, stage_bounds):
        
        if self.hitstun > 0:
            self.hitstun -= dt
            if self.hitstun <= 0:
                self.hitstun = 0
                
                self.state = "idle"
        
        if not self.grounded:
            self.vy += GRAVITY * dt
            self.y += self.vy * dt
            self.air_time += dt
            if self.y >= GROUND_Y:
                self.y = GROUND_Y
                self.grounded = True
                self.vy = 0
                self.jumping = False
                self.air_time = 0.0
                
                if self.state == "air_hit":
                    self.state = "down"
                    self.state_timer = 0.6
        
        if self.state not in ("attack", "hit", "throw", "down") and not self.blocking and not self.stunned:
            self.vx *= pow(0.001, dt)  
        
        self.x += self.vx * dt
        
        left, right = stage_bounds
        self.x = clamp(self.x, left + self.width//2, right - self.width//2)
        
        if opponent:
            if opponent.x > self.x:
                self.facing = 1
            else:
                self.facing = -1
        
        if self.state_timer > 0:
            self.state_timer -= dt
            if self.state_timer <= 0:
                
                if self.state in ("attack",):
                    
                    self.state = "idle"
                elif self.state == "down":
                    
                    self.state = "idle"
                elif self.state == "throw":
                    self.state = "idle"
                elif self.state == "block":
                    self.blocking = False
                    self.state = "idle"
       
        self.health = clamp(self.health, 0, self.max_health)

    def apply_input(self, keys, dt):
        """Apply directional/input commands when not stunned/hit."""
        if self.hitstun > 0 or self.state in ("hit", "throw", "down"):
            return
        move_speed = self.stats["speed"]
        left = keys.get("left", False)
        right = keys.get("right", False)
        up = keys.get("up", False)
        down = keys.get("down", False)
        block = keys.get("block", False)
        
        self.blocking = block
        if block:
            self.state = "block"
            self.state_timer = 0.016  
            
            self.vx *= 0.8
            return
        
        if left and not right:
            self.vx = -move_speed
            self.state = "walk"
        elif right and not left:
            self.vx = move_speed
            self.state = "walk"
        else:
            if abs(self.vx) < 1:
                self.vx = 0
                if self.state == "walk":
                    self.state = "idle"
        
        self.crouching = down and self.grounded
        
        if up and self.grounded:
            self.vy = -self.stats["jump_power"]
            self.grounded = False
            self.jumping = True
            self.state = "jump"
            self.state_timer = 0.12

    def attack(self, attack_name, opponent):
        
        if self.hitstun > 0 or self.state in ("attack", "throw", "down", "hit"):
            return False
        if attack_name not in self.attacks:
            return False
        startup, active, recovery, damage, hitstun, knockback = self.attacks[attack_name]
        total_duration = startup + active + recovery
        self.state = "attack"
        self.state_timer = total_duration
        self.anim_timer = 0.0
        
        self.attack_queue.append({
            "name": attack_name,
            "startup": startup,
            "active": active,
            "recovery": recovery,
            "damage": damage,
            "hitstun": hitstun,
            "knockback": knockback,
            "t": 0.0,
            "hit": False
        })
        return True

    def update_attacks(self, dt, opponent, game):
        
        if not self.attack_queue:
            return
        a = self.attack_queue[0]
        a["t"] += dt
        
        self.anim_timer = a["t"]
        
        if a["startup"] <= a["t"] <= (a["startup"] + a["active"]) and not a["hit"]:
            
            direction = self.facing
            reach = self.stats["reach"]
            hitbox = pygame.Rect(0, 0, reach + 24, 28)
            
            base = self.rect()
            if direction == 1:
                hitbox.midleft = (base.centerx + 16, base.centery - 20)
            else:
                hitbox.midright = (base.centerx - 16, base.centery - 20)
            
            opp_rect = opponent.rect()
            if hitbox.colliderect(opp_rect):
                
                blocked = False
                
                if opponent.blocking and (opponent.facing == -direction):
                    blocked = True
                
                if blocked:
                    dmg = int(a["damage"] * 0.25 * opponent.stats["defense"])
                    opponent.health -= dmg
                    opponent.hitstun = a["hitstun"] * 0.6
                    
                    opponent.vx += (a["knockback"] * 0.2) * direction
                    
                    game.spawn_effect("block", hitbox.center)
                    game.camera_shake(6)
                    game.play_sound("block")
                else:
                    
                    dmg = int(a["damage"] * (1.0 / opponent.stats["defense"]))
                    opponent.health -= dmg
                    opponent.hitstun = a["hitstun"]
                    
                    if not opponent.grounded:
                        opponent.vy = -200  
                        opponent.state = "air_hit"
                    else:
                        opponent.vx += (a["knockback"] / opponent.stats["weight"]) * direction
                        opponent.state = "hit"
                    
                    self.combo_counter += 1
                    opponent.combo_counter = 0
                    game.spawn_effect("hit", hitbox.center)
                    game.camera_shake(12)
                    game.play_sound("hit")
                a["hit"] = True

        if a["t"] >= (a["startup"] + a["active"] + a["recovery"]):
            self.attack_queue.popleft()

    def throw(self, opponent, game):
        
        if self.state in ("attack", "throw", "hit") or self.hitstun > 0:
            return False
        
        if abs(self.x - opponent.x) < (self.width * 0.9):
            
            self.state = "throw"
            self.state_timer = self.attacks["throw"][0] + self.attacks["throw"][1] + self.attacks["throw"][2]
            opponent.health -= self.attacks["throw"][3]
            opponent.hitstun = self.attacks["throw"][4]
            opponent.vx = 200 * self.facing
            opponent.vy = -200
            opponent.grounded = False
            opponent.state = "air_hit"
            game.spawn_effect("throw", ( (self.x + opponent.x)/2, self.y - 40 ))
            game.camera_shake(18)
            game.play_sound("throw")
            return True
        return False

    def draw(self, surf, offset=(0, 0)):
        """Draw the fighter using simple procedural shapes."""
        ox, oy = offset
        r = self.rect()
        
        base = pygame.Rect(r.left + ox, r.top + oy, r.width, r.height)
        
        torso = pygame.Rect(base.left + base.width*0.15, base.top + base.height*0.15, base.width*0.7, base.height*0.55)
        
        head = pygame.Rect(base.centerx - 20, base.top - 28, 40, 40)
        
        left_leg = pygame.Rect(base.left + 6, base.bottom - 32, base.width*0.38, 32)
        right_leg = pygame.Rect(base.right - 6 - int(base.width*0.38), base.bottom - 32, base.width*0.38, 32)
        
        col = self.color
        main = col
        dark = tuple(max(0, int(c*0.7)) for c in col)
        light = tuple(min(255, int(c*1.15)) for c in col)
        
        leg_sway = math.sin(now()*6 + self.x*0.01) * 6 if self.state == "walk" else 0
        pygame.draw.rect(surf, dark, left_leg.move(0, leg_sway))
        pygame.draw.rect(surf, dark, right_leg.move(0, -leg_sway))
        # torso
        pygame.draw.rect(surf, main, torso)
        # outline
        pygame.draw.rect(surf, self.outline, torso, 2, border_radius=6)
        # head
        pygame.draw.ellipse(surf, light, head)
        pygame.draw.ellipse(surf, self.outline, head, 2)
        # arms (simple)
        arm_w = 12
        left_arm = pygame.Rect(torso.left - arm_w, torso.top + 8, arm_w, int(torso.height*0.9))
        right_arm = pygame.Rect(torso.right, torso.top + 8, arm_w, int(torso.height*0.9))
        
        if self.state == "attack" and self.attack_queue:
            a = self.attack_queue[0]
            
            prog = a["t"] / max(0.0001, (a["startup"] + a["active"] + a["recovery"]))
            swing = -60 + prog * 120
            if self.facing == -1:
                swing = -swing
            
            if a["name"] in ("jab", "strong", "special"):
                
                if self.facing == 1:
                    
                    ex = torso.centerx + 40 * math.cos(math.radians(swing))
                    ey = torso.centery - 30 * math.sin(math.radians(swing))
                    pygame.draw.line(surf, light, (torso.centerx, torso.centery - 10), (ex, ey), 8)
                else:
                    ex = torso.centerx - 40 * math.cos(math.radians(swing))
                    ey = torso.centery - 30 * math.sin(math.radians(swing))
                    pygame.draw.line(surf, light, (torso.centerx, torso.centery - 10), (ex, ey), 8)
        
        pygame.draw.rect(surf, dark, left_arm)
        pygame.draw.rect(surf, dark, right_arm)
        name_surf = pygame.font.SysFont("Arial", 14, bold=True).render(self.name, True, (240,240,240))
        surf.blit(name_surf, (r.left + ox, r.top + oy - 22))


class Stage:
    def __init__(self, idx):
        self.idx = idx
        self.bg_colors = STAGE_COLORS[idx % len(STAGE_COLORS)]
        self.ground_color = (80, 80, 80)
        
        self.music_pitch = 220 + idx * 40

    def draw(self, surf, offset=(0, 0)):
        left_col, right_col = self.bg_colors
        
        for i in range(HEIGHT):
            t = i / HEIGHT
            r = int(left_col[0]*(1-t) + right_col[0]*t)
            g = int(left_col[1]*(1-t) + right_col[1]*t)
            b = int(left_col[2]*(1-t) + right_col[2]*t)
            pygame.draw.line(surf, (r,g,b), (0, i), (WIDTH, i))
        
        pygame.draw.rect(surf, self.ground_color, (0, GROUND_Y + 1, WIDTH, HEIGHT - GROUND_Y))
        
        pygame.draw.rect(surf, (30,30,30), (0, 0, 80, HEIGHT))
        pygame.draw.rect(surf, (30,30,30), (WIDTH-80, 0, 80, HEIGHT))


class Effect:
    def __init__(self, kind, pos, life=0.5):
        self.kind = kind
        self.pos = pos
        self.life = life
        self.t = 0.0

    def update(self, dt):
        self.t += dt

    def done(self):
        return self.t >= self.life

    def draw(self, surf, offset=(0,0)):
        x, y = self.pos
        ox, oy = offset
        progress = clamp(self.t / max(0.0001, self.life), 0.0, 1.0)
        if self.kind == "hit":
            size = 6 + 28 * progress
            pygame.draw.circle(surf, (255, 210, 20), (int(x+ox), int(y+oy)), int(size))
            pygame.draw.circle(surf, (180, 80, 20), (int(x+ox), int(y+oy)), int(size*0.6), 2)
        elif self.kind == "block":
            size = 12 + 10 * progress
            pygame.draw.circle(surf, (120, 200, 255), (int(x+ox), int(y+oy)), int(size), 3)
        elif self.kind == "throw":
            size = 10 + 24 * progress
            pygame.draw.rect(surf, (255,190,180), (int(x+ox-size/2), int(y+oy-size/2), int(size), int(size/2)))
        elif self.kind == "spark":
            for i in range(6):
                ang = i * (math.pi * 2 / 6) + progress * 6
                sx = x + math.cos(ang) * (10 + progress*20)
                sy = y + math.sin(ang) * (6 + progress*14)
                pygame.draw.circle(surf, (255,255,200), (int(sx+ox), int(sy+oy)), 3)


class AIController:
    def __init__(self, fighter, difficulty=0.6):
        self.fighter = fighter
        self.difficulty = difficulty
        self.timer = 0.0
        self.cooldown = 0.6

    def update(self, dt, opponent, game):
        self.timer -= dt
        
        if self.fighter.hitstun > 0:
            return
        
        dist = opponent.x - self.fighter.x
        absd = abs(dist)
        
        if self.timer <= 0:
            self.timer = self.cooldown * (0.5 + random.random()*1.5*(1-self.difficulty))
            
            if absd < 80:
                if random.random() < 0.25:
                    self.fighter.throw(opponent, game)
                else:
                    choice = random.choice(["jab", "strong", "low", "roundhouse"])
                    self.fighter.attack(choice, opponent)
            elif absd < 250:
                if random.random() < 0.6 * self.difficulty:
                    self.fighter.attack(random.choice(["jab", "strong"]), opponent)
                else:
                    self.move_toward(opponent, dt)
            else:
                if random.random() < 0.6:
                    self.move_toward(opponent, dt)
                else:
                    if random.random() < 0.1 * self.difficulty and self.fighter.grounded:
                        self.fighter.vy = -self.fighter.stats["jump_power"]
                        self.fighter.grounded = False
        if opponent.state == "attack" and absd < 180 and random.random() < 0.6 * self.difficulty:
            self.fighter.blocking = True
            self.fighter.state = "block"
            self.fighter.state_timer = 0.2

    def move_toward(self, opponent, dt):
        if opponent.x > self.fighter.x:
            self.fighter.vx = min(self.fighter.stats["speed"], self.fighter.vx + 40)
        else:
            self.fighter.vx = max(-self.fighter.stats["speed"], self.fighter.vx - 40)


class SoundManager:
    def __init__(self):
        pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=2)
        self.sounds = {}
        if NUMPY_AVAILABLE:
            self.sounds["hit"] = generate_tone(880, 0.08, 0.2)
            self.sounds["block"] = generate_tone(560, 0.06, 0.16)
            self.sounds["throw"] = generate_tone(440, 0.1, 0.18)
            self.sounds["round_start"] = generate_tone(330, 0.6, 0.2)
            self.sounds["ko"] = generate_tone(110, 0.9, 0.28)
            self.sounds["select"] = generate_tone(770, 0.05, 0.12)
        else:
            pass

    def play(self, name):
        s = self.sounds.get(name)
        if s:
            s.play()


class Game:
    def __init__(self):
        pygame.mixer.pre_init(44100, -16, 2)
        pygame.init()

        pygame.display.set_caption("Cheap God of War")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("Arial", 24)
        self.bigfont = pygame.font.SysFont("Arial", 40, bold=True)
        self.running = True
        self.state = "menu"  
        self.buttons = []
        self.create_menu()
        self.players = [
            {"name": "Ryuji", "color": (220,40,40), "stats": {"speed": 380, "attack_damage": 70, "weight": 1.0}},
            {"name": "Akira", "color": (40,40,220), "stats": {"speed": 420, "attack_damage": 62, "weight": 0.9}},
            {"name": "Mika", "color": (60,200,90), "stats": {"speed": 340, "attack_damage": 84, "weight": 1.1}},
        ]
        self.selected = [0, 1]  
         
        self.stages = [Stage(i) for i in range(3)]
        self.stage_idx = 0  # ✅ Default to first stage to prevent AttributeError
        self.sound = SoundManager()
        
        # jaadooooo haiii
        self.effects = []
        self.camera_offset = [0,0]
        self.camera_shake_timer = 0.0
        self.camera_shake_power = 0.0
        self.fighter1 = None
        self.fighter2 = None
        self.ai_controller = None
        self.round = 1
        self.best_of = 3
        self.score = [0, 0]
        self.round_start_time = 0.0
        self.round_timer = ROUND_TIME
        self.round_over = False
        self.match_over = False
        self.announcer = []
        self.small_font = pygame.font.SysFont("Arial", 18)
        self.menu_music_pitch = 300
        self.instructions_text = [
            "Controls (Player 1): Move - WASD, Block - SPACE, Attacks - F (jab), G (strong), H (low), R (throw)",
            "Controls (Player 2): Move - Arrows, Block - Right Shift, Attacks - NumPad1 (jab), NumPad2 (strong), NumPad3 (low), NumPad0 (throw)",
            "Mechanics: High/Mid/Low attacks, Blocking reduces damage, Throws beat blocks at close range.",
            "Press R after a match to restart. Best of 3 rounds wins.",
        ]



    def create_menu(self):
        w, h = 320, 56
        midx = WIDTH//2
        font = pygame.font.SysFont("Arial", 28, bold=True)
        def start_cb():
            self.state = "char_select"
            self.sound.play("select")
        def instr_cb():
            self.state = "instructions"
            self.sound.play("select")
        def exit_cb():
            pygame.quit()
            sys.exit()
        self.buttons = [
            Button((midx - w//2, 240, w, h), "Start Game", font, start_cb),
            Button((midx - w//2, 310, w, h), "Instructions", font, instr_cb),
            Button((midx - w//2, 380, w, h), "Exit", font, exit_cb),
        ]

    def start_fight(self):
        p1 = self.players[self.selected[0]]
        p2 = self.players[self.selected[1]]
        self.fighter1 = Fighter(p1["name"], WIDTH*0.35, facing=1, color=p1["color"], stats=p1.get("stats", None), controls=P1_KEYS, is_ai=False)
        self.fighter2 = Fighter(p2["name"], WIDTH*0.65, facing=-1, color=p2["color"], stats=p2.get("stats", None), controls=P2_KEYS, is_ai=True)
        self.ai_controller = AIController(self.fighter2, difficulty=0.7)
        self.round = 1
        self.round_timer = ROUND_TIME
        self.round_over = False
        self.match_over = False
        self.score = [0, 0]
        self.announcer = []
        self.round_start_time = now()
        self.state = "fight"
        self.sound.play("round_start")

    def spawn_effect(self, kind, pos):
        self.effects.append(Effect(kind, pos, life=0.5))

    def camera_shake(self, power):
        self.camera_shake_timer = 0.18
        self.camera_shake_power = max(self.camera_shake_power, power)

    def play_sound(self, name):
        self.sound.play(name)

    def update(self, dt):
        if self.state == "menu":
            pass
        elif self.state == "instructions":
            pass
        elif self.state == "char_select":
            pass
        elif self.state == "stage_select":
            pass
        elif self.state == "fight":
            self.update_fight(dt)

        for e in list(self.effects):
            e.update(dt)
            if e.done():
                self.effects.remove(e)
        if self.camera_shake_timer > 0:
            self.camera_shake_timer -= dt
            shake_progress = clamp(self.camera_shake_timer / 0.18, 0.0, 1.0)
            self.camera_offset[0] = random.uniform(-1,1) * self.camera_shake_power * shake_progress
            self.camera_offset[1] = random.uniform(-0.5,0.5) * self.camera_shake_power * shake_progress
            if self.camera_shake_timer <= 0:
                self.camera_offset = [0,0]
                self.camera_shake_power = 0.0

    def update_fight(self, dt):
        if not self.round_over:
            self.round_timer -= dt
            if self.round_timer <= 0:
                self.round_over = True
                if self.fighter1.health > self.fighter2.health:
                    self.score[0] += 1
                    self.announcer.append("Player 1 wins the round!")
                elif self.fighter2.health > self.fighter1.health:
                    self.score[1] += 1
                    self.announcer.append("Player 2 wins the round!")
                else:
                    self.announcer.append("Time Up - Draw")
                if self.score[0] > self.best_of//2 or self.score[1] > self.best_of//2:
                    self.match_over = True
                else:
                    pygame.time.set_timer(pygame.USEREVENT+1, 1200, loops=1)
        keys_pressed = pygame.key.get_pressed()
        p1_keys = {
            "left": keys_pressed[P1_KEYS["left"]],
            "right": keys_pressed[P1_KEYS["right"]],
            "up": keys_pressed[P1_KEYS["up"]],
            "down": keys_pressed[P1_KEYS["down"]],
            "block": keys_pressed[P1_KEYS["block"]],
        }
        p2_keys = {
            "left": keys_pressed[P2_KEYS["left"]],
            "right": keys_pressed[P2_KEYS["right"]],
            "up": keys_pressed[P2_KEYS["up"]],
            "down": keys_pressed[P2_KEYS["down"]],
            "block": keys_pressed[P2_KEYS["block"]],
        }
        if not self.round_over:
            self.fighter1.apply_input(p1_keys, dt)
            
            if keys_pressed[P1_KEYS["p1"]]:
                self.fighter1.attack("jab", self.fighter2)
            if keys_pressed[P1_KEYS["p2"]]:
                self.fighter1.attack("strong", self.fighter2)
            if keys_pressed[P1_KEYS["p3"]]:
                self.fighter1.attack("low", self.fighter2)
            if keys_pressed[P1_KEYS["throw"]]:
                self.fighter1.throw(self.fighter2, self)
            if self.fighter2.is_ai:
                self.ai_controller.update(dt, self.fighter1, self)
            else:
                self.fighter2.apply_input(p2_keys, dt)
                if keys_pressed[P2_KEYS["p1"]]:
                    self.fighter2.attack("jab", self.fighter1)
                if keys_pressed[P2_KEYS["p2"]]:
                    self.fighter2.attack("strong", self.fighter1)
                if keys_pressed[P2_KEYS["p3"]]:
                    self.fighter2.attack("low", self.fighter1)
                if keys_pressed[P2_KEYS["throw"]]:
                    self.fighter2.throw(self.fighter1, self)
        self.fighter1.update(dt, self.fighter2, STAGE_BOUNDS)
        self.fighter2.update(dt, self.fighter1, STAGE_BOUNDS)
        self.fighter1.update_attacks(dt, self.fighter2, self)
        self.fighter2.update_attacks(dt, self.fighter1, self)
        r1 = self.fighter1.rect()
        r2 = self.fighter2.rect()
        if r1.colliderect(r2):
            overlap = (r1.right - r2.left) if r1.centerx < r2.centerx else (r2.right - r1.left)
            if self.fighter1.x < self.fighter2.x:
                self.fighter1.x -= overlap/2
                self.fighter2.x += overlap/2
            else:
                self.fighter1.x += overlap/2
                self.fighter2.x -= overlap/2
            self.fighter1.vx *= 0.6
            self.fighter2.vx *= 0.6
        if not self.round_over:
            if self.fighter1.health <= 0 or self.fighter2.health <= 0:
                self.round_over = True
                if self.fighter1.health <= 0 and self.fighter2.health <= 0:
                    self.announcer.append("Double KO!")
                elif self.fighter1.health <= 0:
                    self.score[1] += 1
                    self.announcer.append("Player 2 wins the round!")
                else:
                    self.score[0] += 1
                    self.announcer.append("Player 1 wins the round!")
                self.sound.play("ko")
                if self.score[0] > self.best_of//2 or self.score[1] > self.best_of//2:
                    self.match_over = True
                else:
                    pygame.time.set_timer(pygame.USEREVENT+1, 1200, loops=1)

    def reset_round(self):
        self.fighter1.x = WIDTH*0.35
        self.fighter1.health = self.fighter1.max_health
        self.fighter1.vx = 0
        self.fighter1.vy = 0
        self.fighter1.hitstun = 0
        self.fighter1.state = "idle"
        self.fighter2.x = WIDTH*0.65
        self.fighter2.health = self.fighter2.max_health
        self.fighter2.vx = 0
        self.fighter2.vy = 0
        self.fighter2.hitstun = 0
        self.fighter2.state = "idle"
        self.round += 1
        self.round_timer = ROUND_TIME
        self.round_over = False
        self.announcer = []
        self.camera_offset = [0,0]

    def draw(self):
        if self.state == "menu":
            self.draw_menu()
        elif self.state == "instructions":
            self.draw_instructions()
        elif self.state == "char_select":
            self.draw_char_select()
        elif self.state == "stage_select":
            self.draw_stage_select()
        elif self.state == "fight":
            self.draw_fight()

    def draw_menu(self):
        for i in range(HEIGHT):
            t = i / HEIGHT
            c = int(20*(1-t) + 80*t)
            pygame.draw.line(self.screen, (c, c, c), (0,i), (WIDTH,i))
        title = self.bigfont.render("Cheap God of War", True, (240,240,240))
        self.screen.blit(title, title.get_rect(center=(WIDTH//2, 120)))
        sub = self.font.render("A procedural Tekken-like 2D cheap-god-of-war  fighter game (no external assets)", True, (200,200,200))
        self.screen.blit(sub, sub.get_rect(center=(WIDTH//2, 180)))
        for b in self.buttons:
            b.draw(self.screen)

    def draw_instructions(self):
        self.screen.fill((30,30,30))
        title = self.bigfont.render("Instructions", True, (240,240,240))
        self.screen.blit(title, (60, 36))
        y = 120
        for line in self.instructions_text:
            surf = self.small_font.render(line, True, (220,220,220))
            self.screen.blit(surf, (60, y))
            y += 36
        back = self.small_font.render("Press ESC to go back", True, (160,160,160))
        self.screen.blit(back, (60, HEIGHT - 60))

    def draw_char_select(self):
        self.screen.fill((18, 18, 30))
        title = self.bigfont.render("Character Select", True, (240,240,240))
        self.screen.blit(title, (60, 36))
        card_w, card_h = 220, 270
        margin = 40
        total = len(self.players)
        startx = WIDTH//2 - ((card_w+margin)*(total-1) + card_w)/2
        for i, p in enumerate(self.players):
            rect = pygame.Rect(startx + i*(card_w+margin), 140, card_w, card_h)
            pygame.draw.rect(self.screen, (10,10,10), rect, border_radius=8)
            mini = Fighter(p["name"], rect.centerx, color=p["color"], stats=p.get("stats",None))
            sur = pygame.Surface((card_w, card_h), pygame.SRCALPHA)
            mini.y = rect.height - 30
            mini.x = rect.width//2
            mini.draw(sur, offset=(0,0))
            self.screen.blit(sur, (rect.left, rect.top))
            name = self.small_font.render(p["name"], True, (240,240,240))
            self.screen.blit(name, (rect.left + 8, rect.bottom - 30))
            sel1 = "P1" if self.selected[0] == i else ""
            sel2 = "P2" if self.selected[1] == i else ""
            sel = self.small_font.render(f"{sel1} {sel2}", True, (200,200,120))
            self.screen.blit(sel, (rect.left + 8, rect.bottom - 10))
        info = self.small_font.render("Use Left/Right to change P1 selection, A/D to change P2 selection, Enter to proceed", True, (200,200,200))
        self.screen.blit(info, (60, HEIGHT - 60))

    def draw_stage_select(self):
        self.screen.fill((20, 20, 40))
        title = self.bigfont.render("Stage Select", True, (240,240,240))
        self.screen.blit(title, (60, 36))
        y = 160
        for i, st in enumerate(self.stages):
            rect = pygame.Rect(120, y, WIDTH - 240, 120)
            pygame.draw.rect(self.screen, (30,30,30), rect, border_radius=10)
            name = self.small_font.render(f"Stage {i+1}", True, (240,240,240))
            self.screen.blit(name, (rect.left + 12, rect.top + 8))
            preview = pygame.Surface((200, 96))
            for r_i in range(96):
                t = r_i/96
                lc = st.bg_colors[0]
                rc = st.bg_colors[1]
                rr = int(lc[0]*(1-t) + rc[0]*t)
                rg = int(lc[1]*(1-t) + rc[1]*t)
                rb = int(lc[2]*(1-t) + rc[2]*t)
                pygame.draw.line(preview, (rr,rg,rb), (0, r_i), (200, r_i))
            self.screen.blit(preview, (rect.right - 220, rect.top + 12))
            y += 140
        info = self.small_font.render("Press Enter to start fight on selected stage", True, (200,200,200))
        self.screen.blit(info, (60, HEIGHT - 60))

    def draw_fight(self):
        stage = self.stages[self.stage_idx]
        stage.draw(self.screen, offset=self.camera_offset)
        for f in (self.fighter1, self.fighter2):
            f.draw(self.screen, offset=self.camera_offset)
        for e in self.effects:
            e.draw(self.screen, offset=self.camera_offset)
        pad = 48
        bar_w = 520
        bar_h = 28
        x1 = pad
        y = 24
        pygame.draw.rect(self.screen, (10,10,10), (x1-4, y-4, bar_w+8, bar_h+8), border_radius=6)
        h_frac1 = self.fighter1.health / self.fighter1.max_health
        pygame.draw.rect(self.screen, (120,20,20), (x1, y, int(bar_w*h_frac1), bar_h), border_radius=6)
        name1 = self.small_font.render(self.fighter1.name, True, (240,240,240))
        self.screen.blit(name1, (x1, y + bar_h + 4))
        x2 = WIDTH - pad - bar_w
        pygame.draw.rect(self.screen, (10,10,10), (x2-4, y-4, bar_w+8, bar_h+8), border_radius=6)
        h_frac2 = self.fighter2.health / self.fighter2.max_health
        pygame.draw.rect(self.screen, (20,20,140), (x2, y, int(bar_w*h_frac2), bar_h), border_radius=6)
        name2 = self.small_font.render(self.fighter2.name, True, (240,240,240))
        self.screen.blit(name2, (x2 + bar_w - name2.get_width(), y + bar_h + 4))
        timer_text = self.bigfont.render(str(int(self.round_timer)), True, (240,240,240))
        self.screen.blit(timer_text, timer_text.get_rect(center=(WIDTH//2, 36)))
        score_text = self.font.render(f"Round {self.round}   Score {self.score[0]} - {self.score[1]}", True, (220,220,220))
        self.screen.blit(score_text, (WIDTH//2 - score_text.get_width()//2, 72))
        for i, m in enumerate(self.announcer[-3:]):
            a = self.small_font.render(m, True, (255,240,220))
            self.screen.blit(a, (WIDTH//2 - a.get_width()//2, 140 + i*26))
        if self.round_over:
            text = "Round Over"
            surf = self.bigfont.render(text, True, (255,200,80))
            self.screen.blit(surf, surf.get_rect(center=(WIDTH//2, HEIGHT//2 - 40)))
            sub = self.small_font.render("Press R to restart/continue", True, (200,200,200))
            self.screen.blit(sub, sub.get_rect(center=(WIDTH//2, HEIGHT//2 + 10)))
        if self.match_over:
            winner = "Player 1" if self.score[0] > self.score[1] else "Player 2"
            text = f"{winner} Wins the Match!"
            surf = self.bigfont.render(text, True, (120, 255, 120))
            self.screen.blit(surf, surf.get_rect(center=(WIDTH//2, HEIGHT//2 - 120)))
            sub = self.small_font.render("Press R to restart match or ESC to go to menu", True, (200,200,200))
            self.screen.blit(sub, sub.get_rect(center=(WIDTH//2, HEIGHT//2 - 60)))
        hints = self.small_font.render("P1: WASD move, SPACE block, F/G/H attacks. P2: Arrows, RSHIFT block, Numpad attacks", True, (180,180,180))
        self.screen.blit(hints, (60, HEIGHT - 40))

    def handle_event(self, event):
        if self.state == "menu":
            for b in self.buttons:
                b.handle_event(event)
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_RETURN:
                    self.state = "char_select"
        elif self.state == "instructions":
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self.state = "menu"
        elif self.state == "char_select":
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_LEFT:
                    self.selected[0] = (self.selected[0] - 1) % len(self.players)
                elif event.key == pygame.K_RIGHT:
                    self.selected[0] = (self.selected[0] + 1) % len(self.players)
                elif event.key == pygame.K_a:
                    self.selected[1] = (self.selected[1] - 1) % len(self.players)
                elif event.key == pygame.K_d:
                    self.selected[1] = (self.selected[1] + 1) % len(self.players)
                elif event.key == pygame.K_RETURN:
                    self.state = "stage_select"
        elif self.state == "stage_select":
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_LEFT:
                    self.stage_idx = (self.stage_idx - 1) % len(self.stages)
                elif event.key == pygame.K_RIGHT:
                    self.stage_idx = (self.stage_idx + 1) % len(self.stages)
                elif event.key == pygame.K_RETURN:
                    self.start_fight()
                elif event.key == pygame.K_ESCAPE:
                    self.state = "char_select"
        elif self.state == "fight":
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_r:
                    if self.match_over:
                        self.start_fight()
                    else:
                        if self.round_over:
                            if not self.match_over:
                                self.reset_round()
                if event.key == pygame.K_ESCAPE:
                    self.state = "menu"
            if event.type == pygame.USEREVENT+1:
                if not self.match_over:
                    self.reset_round()

    def run(self):
        last = time.time()
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                self.handle_event(event)
            self.update(dt)
             
            self.draw()
            pygame.display.flip()
        pygame.quit()

if __name__ == "__main__":
    game = Game()
    game.run()
