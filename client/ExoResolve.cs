// Runtime resolution of obfuscated EFT members (GClassNNNN / method_N / Field_N) by signature or IL role,
// so the EXO-3 hooks survive renames between client builds. Every lookup throws a clear error when it is
// not unique; callers disable only the affected feature.
using System;
using System.Linq;
using System.Reflection;
using System.Reflection.Emit;
using HarmonyLib;

namespace JuggernautClient
{
    internal static class ExoResolve
    {
        private const BindingFlags Inst = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        private const BindingFlags InstDecl = Inst | BindingFlags.DeclaredOnly;

        internal static MethodInfo SingleMethod(Type type, string what, Func<MethodInfo, bool> match)
        {
            var found = type.GetMethods(InstDecl).Where(match).ToArray();
            if (found.Length != 1)
                throw new MissingMethodException($"{what}: expected 1 match on {type.FullName}, found {found.Length}");
            return found[0];
        }

        internal static bool Params(MethodInfo m, params Type[] types) =>
            m.GetParameters().Select(p => p.ParameterType).SequenceEqual(types);

        /// <summary>Instance field of the given type declared on the type or its bases (must be unique).</summary>
        internal static FieldInfo SingleField(Type type, Type fieldType, string what)
        {
            var found = AccessTools.GetDeclaredFields(type).Concat(type.BaseType != null ? AccessTools.GetDeclaredFields(type.BaseType) : Enumerable.Empty<FieldInfo>())
                .Where(f => !f.IsStatic && f.FieldType == fieldType).Distinct().ToArray();
            if (found.Length != 1)
                throw new MissingFieldException($"{what}: expected 1 {fieldType.Name} field on {type.FullName}, found {found.Length}");
            return found[0];
        }

        /// <summary>Last field of fieldType written (stfld) by the method body.</summary>
        internal static FieldInfo LastStoredField(MethodBase method, Type fieldType, string what)
        {
            var stores = PatchProcessor.ReadMethodBody(method)
                .Where(i => i.Key == OpCodes.Stfld && i.Value is FieldInfo f && f.FieldType == fieldType)
                .Select(i => (FieldInfo)i.Value).ToArray();
            if (stores.Length == 0) throw new MissingFieldException($"{what}: no {fieldType.Name} store in {method}");
            return stores[stores.Length - 1];
        }

        /// <summary>Getter for a float value by name fragment: prefers a property, falls back to a field.</summary>
        internal static Func<object, float> FloatMember(Type type, string fragment)
        {
            var prop = type.GetProperties(Inst).FirstOrDefault(p => p.Name == fragment && p.PropertyType == typeof(float) && p.GetGetMethod(true) != null);
            if (prop != null) return o => (float)prop.GetValue(o);
            var field = AccessTools.GetDeclaredFields(type).FirstOrDefault(f => !f.IsStatic && f.FieldType == typeof(float) && f.Name.StartsWith(fragment, StringComparison.Ordinal));
            if (field != null) return o => (float)field.GetValue(o);
            throw new MissingMemberException(type.FullName, fragment);
        }
    }
}
