# Effect-parse audit — unmarked

30 cards: every tricky kind, then random successful parses.
Mark each verdict; a row left unmarked is a row not audited. The
sample answers *precision* — recall is the coverage report's job, and
the two numbers must never be merged.

## Trapjaw Tyrant  *(seeded: ability word)*

`Creature — Dinosaur` · coverage 100%

**Oracle text**

```
Enrage — Whenever this creature is dealt damage, exile target creature an opponent controls until this creature leaves the battlefield.
```

**Parsed**

- `ability_word(name='enrage')` — triggered [this creature is dealt damage]
- `exile(target='target creature an opponent controls until this creature leaves the battlefield')` — triggered [this creature is dealt damage]

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Cryptic Command  *(seeded: modal bullets)*

`Instant` · coverage 100%

**Oracle text**

```
Choose two —
• Counter target spell.
• Return target permanent to its owner's hand.
• Tap all creatures your opponents control.
• Draw a card.
```

**Parsed**

- `modal(count='two')` — spell
- `counter_spell(target='spell')` — spell
- `return_to_hand(target='target permanent')` — spell
- `tap(target='all creatures your opponents control')` — spell
- `draw(amount=1)` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Liliana of the Veil  *(seeded: planeswalker U+2212)*

`Legendary Planeswalker — Liliana` · coverage 75%

**Oracle text**

```
+1: Each player discards a card.
−2: Target player sacrifices a creature.
−6: Separate all permanents target player controls into two piles. That player sacrifices all permanents in the pile of their choice.
```

**Parsed**

- `discard(amount=1)` — spell
- `sacrifice(what='a creature')` — spell
- `sacrifice(what='all permanents in the pile of their choice')` — spell
- ✗ unparsed: `−6: Separate all permanents target player controls into two piles`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## History of Benalia  *(seeded: saga chapters)*

`Enchantment — Saga` · coverage 100%

**Oracle text**

```
(As this Saga enters and after your draw step, add a lore counter. Sacrifice after III.)
I, II — Create a 2/2 white Knight creature token with vigilance.
III — Knights you control get +2/+1 until end of turn.
```

**Parsed**

- `create_token(amount=1, what='2/2 white Knight creature')` — spell
- `pump(target='III — Knights you control', amount='+2/+1')` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Batterskull  *(seeded: costed keyword, no colon)*

`Artifact — Equipment` · coverage 100%

**Oracle text**

```
Living weapon (When this Equipment enters, create a 0/0 black Phyrexian Germ creature token, then attach this to it.)
Equipped creature gets +4/+4 and has vigilance and lifelink.
{3}: Return this Equipment to its owner's hand.
Equip {5}
```

**Parsed**

- `pump(target='Equipped creature', amount='+4/+4')` — spell
- `return_to_hand(target='this Equipment')` — activated [{3}]
- `keyword(name='equip', param='{5}')` — keyword

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Sylvan Library  *(seeded: reminder text with colon)*

`Enchantment` · coverage 33%

**Oracle text**

```
At the beginning of your draw step, you may draw two additional cards. If you do, choose two cards in your hand drawn this turn. For each of those cards, pay 4 life or put the card on top of your library.
```

**Parsed**

- `modal(count='two')` — triggered [the beginning of your draw step]
- ✗ unparsed: `you may draw two additional cards`
- ✗ unparsed: `For each of those cards, pay 4 life or put the card on top of your library`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Akroma, Angel of Wrath  *(seeded: four keywords, one line)*

`Legendary Creature — Angel` · coverage 0%

**Oracle text**

```
Flying, first strike, vigilance, trample, haste, protection from black and from red
```

**Parsed**

- ✗ unparsed: `Flying, first strike, vigilance, trample, haste, protection from black and from red`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Sedge Sliver  *(seeded: quoted grant)*

`Creature — Sliver` · coverage 100%

**Oracle text**

```
All Sliver creatures have "This creature gets +1/+1 as long as you control a Swamp."
All Slivers have "{B}: Regenerate this permanent." (The next time it would be destroyed this turn, instead tap it, remove it from combat, and heal all damage on it.)
```

**Parsed**

- `grant_text(who='All Sliver creatures', text='This creature gets +1/+1 as long as you control a Swamp.')` — spell
- `grant_text(who='All Slivers', text='{B}: Regenerate this permanent.')` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Caravan Escort  *(seeded: leveler)*

`Creature — Human Knight` · coverage 100%

**Oracle text**

```
Level up {2} ({2}: Put a level counter on this. Level up only as a sorcery.)
LEVEL 1-4
2/2
LEVEL 5+
5/5
First strike
```

**Parsed**

- `keyword(name='level up', param='{2}')` — keyword
- `level_band(from=1, to=4)` — spell
- `stat_line(power='2', toughness='2')` — spell
- `level_band(from=5)` — spell
- `stat_line(power='5', toughness='5')` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Fire // Ice  *(seeded: split faces)*

`Instant` · coverage 67%

**Oracle text**

```
— Fire —
Fire deals 2 damage divided as you choose among one or two targets.
— Ice —
Tap target permanent.
Draw a card.
```

**Parsed**

- ✗ unparsed: `CARDNAME deals 2 damage divided as you choose among one or two targets`
- `tap(target='target permanent')` — spell
- `draw(amount=1)` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Worldly Tutor

`Instant` · coverage 100%

**Oracle text**

```
Search your library for a creature card, reveal it, then shuffle and put the card on top.
```

**Parsed**

- `search_library(what='a creature card, reveal it, then shuffle and put the card on top')` — spell
- `shuffle()` — spell
- `reveal(what='it')` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Phenomenon Investigators

`Creature — Human Detective` · coverage 50%

**Oracle text**

```
As this creature enters, choose Believe or Doubt.
• Believe — Whenever a nontoken creature you control dies, create a 2/2 black Horror enchantment creature token.
• Doubt — At the beginning of your end step, you may return a nonland permanent you own to your hand. If you do, draw a card.
```

**Parsed**

- ✗ unparsed: `As this creature enters, choose Believe or Doubt`
- `create_token(amount=1, what='2/2 black Horror enchantment creature')` — spell
- `draw(amount=1)` — spell
- ✗ unparsed: `• Doubt — At the beginning of your end step, you may return a nonland permanent you own to`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Forsaken Crossroads

`Land` · coverage 40%

**Oracle text**

```
Forsaken Crossroads enters the battlefield tapped.
As Forsaken Crossroads enters the battlefield, choose a color.
When Forsaken Crossroads enters the battlefield, scry 1. If you weren't the starting player, you may untap Forsaken Crossroads instead.
{T}: Add one mana of the chosen color.
```

**Parsed**

- ✗ unparsed: `CARDNAME enters the battlefield tapped`
- ✗ unparsed: `As CARDNAME enters the battlefield, choose a color`
- `scry(amount=1)` — triggered [CARDNAME enters the battlefield]
- `untap(target='CARDNAME instead')` — triggered [CARDNAME enters the battlefield]
- ✗ unparsed: `Add one mana of the chosen color`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Pinecrest Ridge

`Land` · coverage 100%

**Oracle text**

```
{T}: Add {C}.
{T}: Add {R} or {G}. This land doesn't untap during your next untap step.
```

**Parsed**

- `add_mana(mana='{C}')` — activated [{T}]
- `add_mana(mana='{R}')` — activated [{T}]
- `untap(target='during your next untap step')` — activated [{T}]

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Spelljack

`Instant` · coverage 100%

**Oracle text**

```
Counter target spell. If that spell is countered this way, exile it instead of putting it into its owner's graveyard. You may play it without paying its mana cost for as long as it remains exiled. (If it has X in its mana cost, X is 0.)
```

**Parsed**

- `counter_spell(target='spell')` — spell
- `exile(target="it instead of putting it into its owner's graveyard")` — spell
- `may_play()` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Magitek Infantry

`Artifact Creature — Robot Soldier` · coverage 100%

**Oracle text**

```
This creature gets +1/+0 as long as you control another artifact.
{2}{W}: Search your library for a card named Magitek Infantry, put it onto the battlefield tapped, then shuffle.
```

**Parsed**

- `pump(target='This creature', amount='+1/+0')` — spell
- `search_library(what='a card named CARDNAME, put it onto the battlefield tapped, then shuffle')` — activated [{2}{W}]
- `shuffle()` — activated [{2}{W}]

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Boggart Shenanigans

`Kindred Enchantment — Goblin` · coverage 100%

**Oracle text**

```
Whenever another Goblin you control is put into a graveyard from the battlefield, you may have this enchantment deal 1 damage to target player or planeswalker.
```

**Parsed**

- `deal_damage(amount=1, target='target player or planeswalker')` — triggered [another Goblin you control is put into a graveyard from the ]

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Waker of Waves

`Creature — Whale` · coverage 67%

**Oracle text**

```
Creatures your opponents control get -1/-0.
{1}{U}, Discard this card: Look at the top two cards of your library. Put one of them into your hand and the other into your graveyard.
```

**Parsed**

- `pump(target='Creatures your opponents control', amount='-1/-0')` — spell
- `look_at(amount=2)` — activated [{1}{U}, Discard this card]
- ✗ unparsed: `Put one of them into your hand and the other into your graveyard`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Thieves' Auction

`Sorcery` · coverage 33%

**Oracle text**

```
Exile all nontoken permanents. Starting with you, each player chooses one of the exiled cards and puts it onto the battlefield tapped under their control. Repeat this process until all cards exiled this way have been chosen.
```

**Parsed**

- `exile(target='all nontoken permanents')` — spell
- ✗ unparsed: `Starting with you, each player chooses one of the exiled cards and puts it onto the battle`
- ✗ unparsed: `Repeat this process until all cards exiled this way have been chosen`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Traverse the Ulvenwald

`Sorcery` · coverage 100%

**Oracle text**

```
Search your library for a basic land card, reveal it, put it into your hand, then shuffle.
Delirium — If there are four or more card types among cards in your graveyard, instead search your library for a creature or land card, reveal it, put it into your hand, then shuffle.
```

**Parsed**

- `search_library(what='a basic land card, reveal it, put it into your hand, then shuffle')` — spell
- `shuffle()` — spell
- `reveal(what='it')` — spell
- `ability_word(name='delirium')` — spell
- `search_library(what='a creature or land card, reveal it, put it into your hand, then shuffle')` — spell
- `shuffle()` — spell
- `reveal(what='it')` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Defender of Law

`Creature — Human Knight` · coverage 100%

**Oracle text**

```
Flash
Protection from red
```

**Parsed**

- `keyword(name='protection', param='from red')` — keyword

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Goblin Goliath

`Creature — Goblin Mutant` · coverage 50%

**Oracle text**

```
When this creature enters, create a number of 1/1 red Goblin creature tokens equal to the number of opponents you have.
{3}{R}, {T}: If a source you control would deal damage to an opponent this turn, it deals double that damage to that player instead.
```

**Parsed**

- `create_token(amount=1, what='number of 1/1 red Goblin creature')` — triggered [this creature enters]
- ✗ unparsed: `If a source you control would deal damage to an opponent this turn, it deals double that d`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Haunting Hymn

`Instant` · coverage 100%

**Oracle text**

```
Target player discards two cards. If you cast this spell during your main phase, that player discards four cards instead.
```

**Parsed**

- `discard(amount=2)` — spell
- `discard(amount=4)` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Vedalken Certarch

`Creature — Vedalken Wizard` · coverage 100%

**Oracle text**

```
Metalcraft — {T}: Tap target artifact, creature, or land. Activate only if you control three or more artifacts.
```

**Parsed**

- `ability_word(name='metalcraft')` — activated [{T}]
- `tap(target='target artifact')` — activated [{T}]
- `timing_restriction(when='if you control three or more artifacts')` — activated [{T}]

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Kroxa and Kunoros

`Legendary Creature — Elder Giant Dog` · coverage 100%

**Oracle text**

```
Vigilance, menace, lifelink
Whenever Kroxa and Kunoros enters or attacks, you may exile five cards from your graveyard. When you do, return target creature card from your graveyard to the battlefield.
```

**Parsed**

- `exile(target='five cards from your graveyard')` — triggered [CARDNAME enters or attacks]
- `return_from_graveyard(target='target creature card')` — triggered [CARDNAME enters or attacks]

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Vedalken Aethermage

`Creature — Vedalken Wizard` · coverage 100%

**Oracle text**

```
Flash (You may cast this spell any time you could cast an instant.)
When this creature enters, return target Sliver to its owner's hand.
Wizardcycling {3} ({3}, Discard this card: Search your library for a Wizard card, reveal it, put it into your hand, then shuffle.)
```

**Parsed**

- `return_to_hand(target='target Sliver')` — triggered [this creature enters]
- `keyword(name='wizardcycling', param='{3}')` — keyword

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Cut a Deal

`Sorcery` · coverage 100%

**Oracle text**

```
Each opponent draws a card, then you draw a card for each opponent who drew a card this way.
```

**Parsed**

- `draw(amount=1)` — spell

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Throne of Makindi

`Land` · coverage 75%

**Oracle text**

```
{T}: Add {C}.
{1}, {T}: Put a charge counter on this land.
{T}, Remove a charge counter from this land: Add two mana of any one color. Spend this mana only to cast kicked spells.
```

**Parsed**

- `add_mana(mana='{C}')` — activated [{T}]
- `put_counters(amount=1, kind='charge', target='this land')` — activated [{1}, {T}]
- `add_mana_any(amount=2)` — activated [{T}, Remove a charge counter from this land]
- ✗ unparsed: `Spend this mana only to cast kicked spells`

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Moonsilver Spear

`Artifact — Equipment` · coverage 67%

**Oracle text**

```
Equipped creature has first strike.
Whenever equipped creature attacks, create a 4/4 white Angel creature token with flying.
Equip {4}
```

**Parsed**

- ✗ unparsed: `Equipped creature has first strike`
- `create_token(amount=1, what='4/4 white Angel creature')` — triggered [equipped creature attacks]
- `keyword(name='equip', param='{4}')` — keyword

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning

## Azula, On the Hunt

`Legendary Creature — Human Noble` · coverage 100%

**Oracle text**

```
Firebending 2 (Whenever this creature attacks, add {R}{R}. This mana lasts until end of combat.)
Whenever Azula attacks, you lose 1 life and create a Clue token. (It's an artifact with "{2}, Sacrifice this token: Draw a card.")
```

**Parsed**

- `keyword(name='firebending', param='2')` — keyword
- `lose_life(amount=1)` — triggered [CARDNAME attacks]
- `create_token(amount=1, what='Clue')` — triggered [CARDNAME attacks]

**Verdict** — [ ] faithful · [ ] wrong verb · [ ] wrong params · [ ] missing meaning
