<p align="center">
  <img src="https://raw.githubusercontent.com/formiification/ha-mobidziennik/main/images/logo@2x.png" alt="mobiDziennik for Home Assistant (unofficial)" height="96">
</p>

# mobiDziennik for Home Assistant (unofficial)

A custom [Home Assistant](https://www.home-assistant.io/) integration that brings data from the Polish school e-register **mobiDziennik** into Home Assistant: timetable (with substitutions and days off), grades and averages, announced tests, homework and unread messages. It supports parent accounts with several children.

> [!IMPORTANT]
> This project is **not affiliated with, endorsed by or connected to Wizja.net**, the company behind mobiDziennik. mobiDziennik has no public API, so this integration reads the regular parent web portal, the same pages you see in a browser. It may stop working whenever the website changes.

## Features

One device is created per student, plus one for the parent account.

| Entity | Example state | Attributes |
|---|---|---|
| Next lesson | `matematyka (09:50)` | date, time, room, teacher, class, substitution |
| Today's lessons | `08:00–14:45 (7)` | list of lessons, substitutions, day off reason |
| Next school day | `Thu 12.11: 08:00–15:20 (8)` | same as above |
| Latest grade | `4+ – biologia` | category, topic, weight, teacher, entered |
| Grades (last 7 days) | `5` | readable list of recent grades |
| Average grade | `4.64` | per-subject weighted averages *(only when the school publishes averages)* |
| Next test | `Thu 12.11 język angielski (sprawdzian)` | days until, topic, list of upcoming tests |
| Homework | `2` (open items) | due date, subject, full content, done flag |
| Unread messages *(account)* | `4` | sender, date and subject of unread messages |

Time-dependent states (next lesson, today) are re-evaluated every minute locally, without contacting the website.

## Being a good citizen

Because this scrapes a website that does not offer an API, the integration deliberately keeps its footprint small:

* **Irregular, infrequent polling.** It polls every 45–75 minutes (randomised every cycle) on school days between 06:00 and 21:00, and every 2.5–3.5 hours at night and at weekends.
* **No bursts.** It waits a random 1–4 s between page loads within one refresh.
* **Minimal requests.** Next week's timetable is only fetched when the current week has no lessons left, and homework details are fetched once per assignment and then cached.
* **Strictly read-only.** It never opens individual messages, so they are not marked as read, and it never changes homework status.

Please do not shorten these intervals.

## Installation

### HACS (custom repository)

1. In HACS, open **⋮ → Custom repositories**.
2. Add `https://github.com/formiification/ha-mobidziennik` with the category **Integration**.
3. Install **mobiDziennik (unofficial)** and restart Home Assistant.

### Manual

Copy `custom_components/mobidziennik` into your `<config>/custom_components/` directory and restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration → mobiDziennik (unofficial)** and enter:

* **School subdomain**: the part before `.mobidziennik.pl`. For example, for `https://myschool.mobidziennik.pl` enter `myschool`.
* **Login / e-mail** and **password**: your parent account credentials.

Credentials are stored in Home Assistant's config entry, like in any other integration, and are only sent to your school's mobiDziennik address.

## Dashboard examples

You do not need to know YAML to use these. Each example is a ready-made card that you paste into your dashboard.

### Step 1: find your child's entity prefix

All entities of one student start with the same prefix, built from the student's name as shown in mobiDziennik. For example, **Kowalski Jan** becomes `sensor.kowalski_jan_…`.

To check yours, open **Settings → Devices & services → Entities**, type `next lesson` in the search box, and look at the entity ID, e.g. `sensor.nowak_zofia_next_lesson`. The prefix is everything before `next_lesson`, here `nowak_zofia`.

### Step 2: add a card

1. Open your dashboard and click **✏️ Edit dashboard**. Choose **Take control** if Home Assistant asks.
2. Click **+ Add card**, scroll down and choose **Manual**.
3. Delete what is in the editor, paste one of the examples below and **replace every `kowalski_jan` with your prefix**. In most editors, *Ctrl + H* (find and replace) does it in one go.
4. Click **Save**.

The examples only use cards that come with Home Assistant, so nothing extra needs to be installed.

---

### 1. At a glance

Six tiles with the most important information. Tap a tile to see the details.

```yaml
type: grid
columns: 2
square: false
cards:
  - type: tile
    entity: sensor.kowalski_jan_next_lesson
    name: Next lesson
  - type: tile
    entity: sensor.kowalski_jan_today_lessons
    name: Today
  - type: tile
    entity: sensor.kowalski_jan_next_test
    name: Next test
  - type: tile
    entity: sensor.kowalski_jan_homework
    name: Open homework
  - type: tile
    entity: sensor.kowalski_jan_latest_grade
    name: Latest grade
  - type: tile
    entity: sensor.kowalski_jan_grades_last_7_days
    name: Grades this week
```

> If your school publishes averages, you can swap the last tile for `sensor.kowalski_jan_average_grade`.

### 2. Today's and the next school day's lessons

A readable lesson plan with rooms. Substitutions are marked ⚠️ and days off are shown with the reason.

```yaml
type: markdown
title: Lessons
content: |-
  {%- set p = 'kowalski_jan' -%}
  {%- macro day(key, label) -%}
  {%- set a = states[key].attributes if states[key] is defined else {} -%}
  **{{ label }}{% if a.date %} · {{ as_datetime(a.date).strftime('%a %d.%m') }}{% endif %}** — {{ 'day off: ' ~ a.day_off if a.day_off else (a.start ~ '–' ~ a.end if a.lesson_count else 'no lessons') }}
  {%- for l in a.lessons or [] %}
  - {{ l | replace('zastępstwo', '⚠️ zastępstwo') }}
  {%- endfor %}
  {%- endmacro -%}
  {{ day('sensor.' ~ p ~ '_today_lessons', 'Today') }}

  {{ day('sensor.' ~ p ~ '_next_school_day', 'Next school day') }}
```

> Here the prefix appears only once, in the first line (`set p = 'kowalski_jan'`).

### 3. Tests and homework

All announced tests with their topics, and homework with the full assignment text. Homework that is already marked as done is crossed out.

```yaml
type: markdown
title: Tests & homework
content: |-
  {%- set p = 'kowalski_jan' -%}
  {%- set t = state_attr('sensor.' ~ p ~ '_next_test', 'upcoming') or [] -%}
  {%- set h = state_attr('sensor.' ~ p ~ '_homework', 'items') or [] -%}
  **📝 Upcoming tests** ({{ t | count }})
  {%- for x in t %}
  - {{ x }}
  {%- else %}
  - none announced
  {%- endfor %}


  **📚 Homework** ({{ states('sensor.' ~ p ~ '_homework') }} open)
  {%- for x in h %}
  - {{ ('~~' ~ x[2:] ~ '~~') if x.startswith('✔') else x }}
  {%- else %}
  - nothing due
  {%- endfor %}
```

### 4. Grades: what's new this week

Each grade is shown first and in bold, followed by the subject, date, category, weight and topic.

```yaml
type: markdown
title: Grades
content: |-
  {%- set p = 'kowalski_jan' -%}
  **Last 7 days** ({{ states('sensor.' ~ p ~ '_grades_last_7_days') }})
  {%- for g in state_attr('sensor.' ~ p ~ '_grades_last_7_days', 'grades') or [] %}
  - {{ g | regex_replace('^(\\d\\d\\.\\d\\d) ([^:]+): (\\S+)', '**\\3** · \\2 · \\1') }}
  {%- else %}
  - no new grades
  {%- endfor %}
```

### 5. Subject averages with traffic lights

Only for schools that publish averages (usually from grade 4 up). 🟢 means 4.5 or more, 🟡 means 3.5–4.49 and 🔴 means below 3.5. Change the numbers if you prefer different thresholds.

```yaml
type: markdown
title: Averages
content: |-
  {%- set p = 'kowalski_jan' -%}
  {%- set avg = 'sensor.' ~ p ~ '_average_grade' -%}
  **Overall: {{ '%.2f' | format(states(avg) | float(0)) }}**

  | Subject | Average |
  |:--|--:|
  {%- for s, v in (state_attr(avg, 'subjects') or {}).items() %}
  | {{ s }} | {{ '🔴' if v < 3.5 else ('🟡' if v < 4.5 else '🟢') }} {{ '%.2f' | format(v) }} |
  {%- endfor %}
```

### 6. Two children side by side

With more than one child, putting their cards in a row keeps each child in their own column, so the information never gets mixed up. Use the same layout for every row: first child on the left, second on the right.

```yaml
type: horizontal-stack
cards:
  - type: tile
    entity: sensor.kowalski_jan_today_lessons
    name: Jan – today
  - type: tile
    entity: sensor.kowalski_ola_today_lessons
    name: Ola – today
```

> **Tip:** you can put any of the examples above inside a `horizontal-stack` in the same way, for example two "Lessons" cards next to each other. Each card can also be shown only to selected users: in the card editor open the **Visibility** tab and choose **User**.

### 7. Unread messages badge

Add this as a **badge** at the top of a view (**Edit dashboard → + Add badge → Manual**). Tapping it opens the inbox in mobiDziennik. Replace `myschool` with your school's subdomain.

```yaml
type: entity
entity: sensor.mobidziennik_unread_messages
name: Unread messages
show_name: true
tap_action:
  action: url
  url_path: https://myschool.mobidziennik.pl/dziennik/wiadomosci
```

### Bonus: a phone notification for every new grade

Go to **Settings → Automations & scenes → + Create automation → ⋮ → Edit in YAML**, paste the code below, replace `kowalski_jan` and `notify.mobile_app_my_phone` with your own (your phone's notify action is listed under **Developer tools → Actions** when you type `notify.mobile_app`), then save.

```yaml
alias: New grade for Jan
triggers:
  - trigger: state
    entity_id: sensor.kowalski_jan_latest_grade
    not_from: ["unknown", "unavailable"]
    not_to: ["unknown", "unavailable"]
actions:
  - action: notify.mobile_app_my_phone
    data:
      title: "New grade: {{ trigger.to_state.attributes.grade }}"
      message: >-
        {{ trigger.to_state.attributes.subject }}
        {%- if trigger.to_state.attributes.category %} ({{ trigger.to_state.attributes.category }}){% endif %}
        {%- if trigger.to_state.attributes.topic %} – {{ trigger.to_state.attributes.topic }}{% endif %}
mode: queued
```

> New data arrives roughly once an hour on school days (see [Being a good citizen](#being-a-good-citizen)), so notifications are not instant.

## Limitations

* It was tested with a primary school using both descriptive (early years) and numeric grades. Other schools may use page variants that are not handled yet. Issues with an **anonymised** HTML snippet are welcome.
* Only the first page of the inbox (the 20 most recent messages) is checked for unread messages.
* Attendance and behaviour notes are not supported yet.

## Troubleshooting

Enable debug logging:

```yaml
logger:
  logs:
    custom_components.mobidziennik: debug
```

When reporting a problem, **remove names, logins and other personal data** from logs and HTML samples.

## License

[MIT](LICENSE)
